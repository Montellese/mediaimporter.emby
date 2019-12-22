#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from datetime import datetime
from dateutil import parser
import json
import posixpath
import sys
import urllib
import urlparse
import uuid

import xbmc
import xbmcaddon
import xbmcgui
from xbmcgui import ListItem
import xbmcmediaimport

import emby
from emby.api import Api
from emby.request import Request
from emby.server import Server

from lib.utils import __addon__, localise, log, mediaProvider2str, Url

# list of fields to retrieve
EMBY_ITEM_FIELDS = [
    emby.constants.PROPERTY_ITEM_PREMIERE_DATE,
    emby.constants.PROPERTY_ITEM_PRODUCTION_YEAR,
    emby.constants.PROPERTY_ITEM_PATH,
    emby.constants.PROPERTY_ITEM_SORT_NAME,
    emby.constants.PROPERTY_ITEM_ORIGINAL_TITLE,
    emby.constants.PROPERTY_ITEM_DATE_CREATED,
    emby.constants.PROPERTY_ITEM_COMMUNITY_RATING,
    emby.constants.PROPERTY_ITEM_VOTE_COUNT,
    emby.constants.PROPERTY_ITEM_OFFICIAL_RATING,
    emby.constants.PROPERTY_ITEM_OVERVIEW,
    emby.constants.PROPERTY_ITEM_SHORT_OVERVIEW,
    emby.constants.PROPERTY_ITEM_TAGLINES,
    emby.constants.PROPERTY_ITEM_GENRES,
    emby.constants.PROPERTY_ITEM_STUDIOS,
    emby.constants.PROPERTY_ITEM_PRODUCTION_LOCATIONS,
    emby.constants.PROPERTY_ITEM_PROVIDER_IDS,
    emby.constants.PROPERTY_ITEM_TAGS,
    emby.constants.PROPERTY_ITEM_PEOPLE,
    emby.constants.PROPERTY_ITEM_ROLE,
    emby.constants.PROPERTY_ITEM_MEDIA_STREAMS,
]

# general constants
ITEM_REQUEST_LIMIT = 100

def mediaTypesFromOptions(options):
    if not 'mediatypes' in options and not 'mediatypes[]' in options:
        return None

    mediaTypes = None
    if 'mediatypes' in options:
        mediaTypes = options['mediatypes']
    elif 'mediatypes[]' in options:
        mediaTypes = options['mediatypes[]']

    return mediaTypes

def getServerId(path):
    if not path:
        return False

    url = urlparse.urlparse(path)
    if url.scheme != emby.constants.EMBY_PROTOCOL or not url.netloc:
        return False

    return url.netloc

def getItemId(path):
    if not path:
        return False

    url = urlparse.urlparse(path)
    urlPath = url.path
    if not urlPath:
        return False

    urlPathParts = []
    while urlPath != '/':
        ( urlPath, subPath ) = posixpath.split(urlPath)
        urlPathParts.insert(0, subPath)

    if len(urlPathParts) < 3:
        return False

    itemId = urlPathParts[2]

    if not itemId:
        return False

    return itemId

def requestUrl(url, authToken='', deviceId='', userId=''):
    headers = Request.PrepareApiCallHeaders(authToken=authToken, deviceId=deviceId, userId=userId)
    return Request.GetAsJson(url, headers=headers)

def preprocessLastPlayed(lastPlayed):
    lastPlayedDate = None
    if lastPlayed:
        lastPlayedDate = parser.parse(lastPlayed)
    if not lastPlayedDate or lastPlayedDate.year < 1900:
        lastPlayedDate = datetime.now()

    return lastPlayedDate

def markAsWatched(embyServer, itemId, lastPlayed):
    lastPlayedDate = preprocessLastPlayed(lastPlayed)

    url = embyServer.BuildUserPlayedItemUrl(itemId)
    url = Url.addOptions(url, { 'DatePlayed': lastPlayedDate.strftime('%Y%m%d%H%M%S') })

    if not embyServer.ApiPost(url):
        return False

    return True

def markAsUnwatched(embyServer, itemId):
    url = embyServer.BuildUserPlayedItemUrl(itemId)

    embyServer.ApiDelete(url)
    return True

def updateResumePoint(embyServer, itemId, positionInTicks):
    url = embyServer.BuildUserPlayingItemUrl(itemId)
    url = Url.addOptions(url, { 'PositionTicks': positionInTicks })

    embyServer.ApiDelete(url)
    return True

def updateUserData(embyServer, itemId, playcount, watched, lastPlayed, playbackPositionInTicks):
    lastPlayedDate = preprocessLastPlayed(lastPlayed)

    url = embyServer.BuildUserItemUserDataUrl(itemId)
    body = {
        'ItemId': itemId,
        'PlayCount': playcount,
        'Played': watched,
        'LastPlayedDate': lastPlayedDate.strftime('%Y-%m-%dT%H:%M:%S.%f%Z'),
        'PlaybackPositionTicks': playbackPositionInTicks
    }

    embyServer.ApiPost(url, body)

def getLibraryViews(embyServer, mediaTypes):
    viewsUrl = embyServer.BuildUserUrl(emby.constants.URL_VIEWS)
    resultObj = embyServer.ApiGet(viewsUrl)
    if not resultObj or not emby.constants.PROPERTY_ITEM_ITEMS in resultObj:
        return []

    viewsObj = resultObj[emby.constants.PROPERTY_ITEM_ITEMS]
    libraryViews = []
    for view in viewsObj:
        if not emby.constants.PROPERTY_VIEW_ID in view or not emby.constants.PROPERTY_VIEW_NAME in view or not emby.constants.PROPERTY_VIEW_COLLECTION_TYPE in view:
            continue

        mediaType = view[emby.constants.PROPERTY_VIEW_COLLECTION_TYPE]
        if not mediaType:
            continue

        matchingMediaTypes = [ type for type in mediaTypes if mediaType == type or mediaType == type + 's' ]
        if not matchingMediaTypes:
            continue

        libraryView = {
            'id': view[emby.constants.PROPERTY_VIEW_ID],
            'name': view[emby.constants.PROPERTY_VIEW_NAME],
            'mediaType': mediaType
        }

        if not libraryView['id'] or not libraryView['name']:
            continue

        libraryViews.append(libraryView)

    return libraryViews

def getLibraryViewsFromSettings(importSettings):
    if not importSettings:
        raise ValueError('invalid importSettings')

    if not importSettings.getString(emby.constants.SETTING_IMPORT_VIEWS) == emby.constants.SETTING_IMPORT_VIEWS_OPTION_SPECIFIC:
        return []

    return importSettings.getStringList(emby.constants.SETTING_IMPORT_VIEWS_SPECIFIC)

def getMatchingLibraryViews(embyServer, mediaTypes, selectedViews):
    if not embyServer:
        raise ValueError('invalid emby server')
    if not mediaTypes:
        raise ValueError('invalid mediaTypes')

    libraryViews = getLibraryViews(embyServer, mediaTypes)

    matchingLibraryViews = []
    if not selectedViews:
        matchingLibraryViews = libraryViews
    else:
        matchingLibraryViews = [ libraryView for libraryView in libraryViews if libraryView['id'] in selectedViews ]

    return matchingLibraryViews

def testAuthentication(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    success = False
    try:
        success = Server(mediaProvider).Authenticate()
    except:
        pass

    title = mediaProvider.getFriendlyName()
    line = 32018
    if success:
        line = 32017
    xbmcgui.Dialog().ok(title, localise(line))

def settingOptionsFillerUsers(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # get the provider's settings
    settings = mediaProvider.getSettings()

    usersUrl = Url.append(mediaProvider.getBasePath(), emby.constants.EMBY_PROTOCOL, emby.constants.URL_USERS, emby.constants.URL_USERS_PUBLIC)
    resultObj = requestUrl(usersUrl, deviceId=settings.getString(emby.constants.SETTING_PROVIDER_DEVICEID))
    if not resultObj:
        return

    users = [ (__addon__.getLocalizedString(32015), emby.constants.SETTING_PROVIDER_USER_OPTION_MANUAL) ]
    for userObj in resultObj:
        # make sure the 'Name' and 'Id' properties are available
        if not emby.constants.PROPERTY_USER_NAME in userObj or not emby.constants.PROPERTY_USER_ID in userObj:
            continue

        # make sure the name and id properties are valid
        name = userObj[emby.constants.PROPERTY_USER_NAME]
        identifier = userObj[emby.constants.PROPERTY_USER_ID]
        if not name or not identifier:
            continue

        # check if the user is disabled
        if emby.constants.PROPERTY_USER_POLICY in userObj and \
           emby.constants.PROPERTY_USER_IS_DISABLED in userObj[emby.constants.PROPERTY_USER_POLICY] and \
           userObj[emby.constants.PROPERTY_USER_POLICY][emby.constants.PROPERTY_USER_IS_DISABLED]:
            continue

        users.append((name, identifier))

    # pass the list of users back to Kodi
    settings.setStringOptions(emby.constants.SETTING_PROVIDER_USER, users)

def settingOptionsFillerViews(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    embyServer = Server(mediaProvider)
    if not embyServer.Authenticate():
        log('failed to authenticate on media provider {}'.format(mediaProvider2str(mediaProvider)), xbmc.LOGERROR)
        return

    libraryViews = getLibraryViews(embyServer, mediaImport.getMediaTypes())
    views = []
    for libraryView in libraryViews:
        views.append((libraryView['name'], libraryView['id']))

    # get the import's settings
    settings = mediaImport.getSettings()

    # pass the list of views back to Kodi
    settings.setStringOptions(emby.constants.SETTING_IMPORT_VIEWS_SPECIFIC, views)

def discoverProvider(handle, options):
    baseUrl = xbmcgui.Dialog().input(localise(32050), 'http://')
    if not baseUrl:
        return

    try:
        result = Server.GetServerInfo(baseUrl)
        if not result:
            return
    except:
        return

    (serverId, providerName, _) = result
    providerId = Server.BuildProviderId(serverId)
    providerIconUrl = Server.BuildIconUrl(baseUrl)

    xbmcmediaimport.setDiscoveredProvider(handle, True, xbmcmediaimport.MediaProvider(providerId, baseUrl, providerName, providerIconUrl, emby.constants.SUPPORTED_MEDIA_TYPES))

def lookupProvider(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    basePath = mediaProvider.getBasePath()

    providerFound = False
    try:
        if Server.GetServerInfo(basePath):
            providerFound = True
    except:
        pass

    xbmcmediaimport.setProviderFound(handle, providerFound)

def canImport(handle, options):
    if not 'path' in options:
        log('cannot execute "canimport" without path')
        return

    path = urllib.unquote(options['path'][0]).decode('utf8')

    # try to get the emby server's identifier from the path
    id = getServerId(path)
    if not id:
      return

    xbmcmediaimport.setCanImport(handle, True)

def isProviderReady(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # check if authentication works with the current provider settings
    providerReady = False
    try:
        providerReady = Server(mediaProvider).Authenticate()
    except:
        pass

    xbmcmediaimport.setProviderReady(handle, providerReady)

def isImportReady(handle, options):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return
    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    embyServer = None
    try:
        embyServer = Server(mediaProvider)
    except:
        return

    importReady = False
    # check if authentication works with the current provider settings
    if embyServer.Authenticate():
        # check if the chosen library views exist
        selectedViews = getLibraryViewsFromSettings(importSettings)
        matchingViews = getMatchingLibraryViews(embyServer, mediaImport.getMediaTypes(), selectedViews)
        importReady = len(matchingViews) > 0

    xbmcmediaimport.setImportReady(handle, importReady)

def loadProviderSettings(handle, options):
    # retrieve the media provider
    mediaProvider = xbmcmediaimport.getProvider(handle)
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    settings = mediaProvider.getSettings()
    if not settings:
        log('cannot retrieve media provider settings', xbmc.LOGERROR)
        return

    # make sure we have a device identifier
    if not settings.getString(emby.constants.SETTING_PROVIDER_DEVICEID):
        settings.setString(emby.constants.SETTING_PROVIDER_DEVICEID, str(uuid.uuid4()))

    settings.registerActionCallback(emby.constants.SETTING_PROVIDER_TEST_AUTHENTICATION, 'testauthentication')

    # register a setting options filler for the list of users
    settings.registerOptionsFillerCallback(emby.constants.SETTING_PROVIDER_USER, 'settingoptionsfillerusers')

    settings.setLoaded()

def loadImportSettings(handle, options):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    settings = mediaImport.getSettings()
    if not settings:
        log('cannot retrieve media import settings', xbmc.LOGERROR)
        return

    # register a setting options filler for the list of views
    settings.registerOptionsFillerCallback(emby.constants.SETTING_IMPORT_VIEWS_SPECIFIC, 'settingoptionsfillerviews')

    settings.setLoaded()

def canUpdateMetadataOnProvider(handle, options):
    xbmcmediaimport.setCanUpdateMetadataOnProvider(True)

def canUpdatePlaycountOnProvider(handle, options):
    xbmcmediaimport.setCanUpdatePlaycountOnProvider(True)

def canUpdateLastPlayedOnProvider(handle, options):
    xbmcmediaimport.setCanUpdateLastPlayedOnProvider(True)

def canUpdateResumePositionOnProvider(handle, options):
    xbmcmediaimport.setCanUpdateResumePositionOnProvider(True)

def execImport(handle, options):
    if not 'path' in options:
        log('cannot execute "import" without path', xbmc.LOGERROR)
        return

    # parse all necessary options
    mediaTypes = mediaTypesFromOptions(options)
    if not mediaTypes:
        log('cannot execute "import" without media types', xbmc.LOGERROR)
        return

    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # create an Emby server instance
    embyServer = Server(mediaProvider)
    if not embyServer.Authenticate():
        log('failed to authenticate on media provider {}'.format(mediaProvider2str(mediaProvider)), xbmc.LOGERROR)
        return

    # build the base URL to retrieve items
    baseUrl = embyServer.BuildUserUrl(emby.constants.URL_ITEMS)
    baseUrlOptions = {
        'Recursive': 'true',
        'Fields': ','.join(EMBY_ITEM_FIELDS),
        'ExcludeLocationTypes': 'Virtual,Offline',
        'Limit': ITEM_REQUEST_LIMIT
    }
    baseUrl = Url.addOptions(baseUrl, baseUrlOptions)

    # get all (matching) library views
    selectedViews = getLibraryViewsFromSettings(importSettings)
    views = getMatchingLibraryViews(embyServer, mediaTypes, selectedViews)
    if not views:
        log('cannot retrieve items without any library views', xbmc.LOGERROR)
        return

    # loop over all media types to be imported
    progress = 0
    progressTotal = len(mediaTypes)
    for mediaType in mediaTypes:
        if xbmcmediaimport.shouldCancel(handle, progress, progressTotal):
            return

        mappedMediaType = Api.getEmbyMediaType(mediaType)
        if not mappedMediaType:
            log('cannot import unsupported media type "{}"'.format(mediaType), xbmc.LOGERROR)
            continue
        (_, embyMediaType, localizedMediaType) = mappedMediaType

        xbmcmediaimport.setProgressStatus(handle, __addon__.getLocalizedString(32001).format(__addon__.getLocalizedString(localizedMediaType)))

        urlOptions = {
            'IncludeItemTypes': embyMediaType
        }
        url = Url.addOptions(baseUrl, urlOptions)

        log('importing {} items from {}'.format(mediaType, url))

        items = []

        # handle library views
        for view in views:
            viewUrl = url
            viewUrl = Url.addOptions(viewUrl, { 'ParentId': view['id'] })

            totalCount = 0
            startIndex = 0
            while True:
                if xbmcmediaimport.shouldCancel(handle, startIndex, max(totalCount, 1)):
                    return

                # put together a paged URL
                pagedUrlOptions = {
                    'StartIndex': startIndex
                }
                pagedUrl = Url.addOptions(viewUrl, pagedUrlOptions)
                resultObj = embyServer.ApiGet(pagedUrl)
                if not resultObj or not emby.constants.PROPERTY_ITEM_ITEMS in resultObj or not emby.constants.PROPERTY_ITEM_TOTAL_RECORD_COUNT in resultObj:
                    log('invalid response for items of media type "{}" from {}'.format(mediaType, pagedUrl), xbmc.LOGERROR)
                    return

                # retrieve the total number of items
                totalCount = int(resultObj[emby.constants.PROPERTY_ITEM_TOTAL_RECORD_COUNT])

                # parse all items
                itemsObj = resultObj[emby.constants.PROPERTY_ITEM_ITEMS]
                for itemObj in itemsObj:
                    startIndex = startIndex + 1
                    if xbmcmediaimport.shouldCancel(handle, startIndex, totalCount):
                        return

                    item = Api.toFileItem(embyServer, itemObj, mediaType, embyMediaType, view['name'])
                    if not item:
                        continue

                    items.append(item)

                # check if we have retrieved all available items
                if startIndex >= totalCount:
                    break

        log('{} {} items imported'.format(len(items), mediaType))
        xbmcmediaimport.addImportItems(handle, items, mediaType)

        progress += 1

    xbmcmediaimport.finishImport(handle)

def updateOnProvider(handle, options):
    # retrieve the media import
    mediaImport = xbmcmediaimport.getImport(handle)
    if not mediaImport:
        log('cannot retrieve media import', xbmc.LOGERROR)
        return

    # retrieve the media provider
    mediaProvider = mediaImport.getProvider()
    if not mediaProvider:
        log('cannot retrieve media provider', xbmc.LOGERROR)
        return

    # prepare and get the media import settings
    importSettings = mediaImport.prepareSettings()
    if not importSettings:
        log('cannot prepare media import settings', xbmc.LOGERROR)
        return

    item = xbmcmediaimport.GetUpdatedItem(handle)
    if not item:
        log('cannot retrieve updated item', xbmc.LOGERROR)
        return

    itemVideoInfoTag = item.getVideoInfoTag()
    if not itemVideoInfoTag:
        log('updated item is not a video item', xbmc.LOGERROR)
        return

    # determine the item's identifier
    itemId = getItemId(itemVideoInfoTag.getPath())
    if not itemId:
        log('cannot determine the identifier of the updated item: "{}"'.format(itemVideoInfoTag.getPath()), xbmc.LOGERROR)
        return

    # prepare the media provider settings
    if not mediaProvider.prepareSettings():
        log('cannot prepare media provider settings', xbmc.LOGERROR)
        return

    # create an Emby server instance
    embyServer = Server(mediaProvider)
    if not embyServer.Authenticate():
        log('failed to authenticate on media provider {}'.format(mediaProvider2str(mediaProvider)), xbmc.LOGERROR)
        return

    # retrieve the version of the Emby server
    useUserDataCall = False
    embyServerInfo = Server.GetServerInfo(embyServer.Url())
    if embyServerInfo:
        (_, _, embyServerVersion) = embyServerInfo
        if embyServerVersion.major >= 4 and embyServerVersion.minor >= 3:
            useUserDataCall = True

    # get the URL to retrieve all details of the item from the Emby server
    getItemUrl = embyServer.BuildUserItemUrl(itemId)

    # retrieve all details of the item
    itemObj = embyServer.ApiGet(getItemUrl)
    if not itemObj:
        log('cannot retrieve details of updated item with id {}'.format(itemId), xbmc.LOGERROR)
        return

    if not emby.constants.PROPERTY_ITEM_USER_DATA in itemObj:
        log('cannot update item with id {} because it has no userdata'.format(itemId), xbmc.LOGERROR)
        return

    updateItemPlayed = False
    updateResumePoint = False
    # retrieve playback states from the updated item
    playcount = itemVideoInfoTag.getPlayCount()
    watched = playcount > 0
    lastPlayed = itemVideoInfoTag.getLastPlayed()
    # retrieve playback position from the updated item
    playbackPositionInSeconds = max(0.0, float(item.getProperty('resumetime')))
    playbackPositionInTicks = Api.secondsToTicks(playbackPositionInSeconds)

    userDataObj = itemObj[emby.constants.PROPERTY_ITEM_USER_DATA]

    # check and update playcout if necessary
    if emby.constants.PROPERTY_ITEM_USER_DATA_PLAY_COUNT in userDataObj:
        # retrieve playcount from the original item
        itemPlayed = userDataObj[emby.constants.PROPERTY_ITEM_USER_DATA_PLAY_COUNT] > 0

        if watched != itemPlayed:
            updateItemPlayed = True

    # check and update playback position if necessary
    if emby.constants.PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS in userDataObj:
        # retrieve playback position from the original item
        itemPlaybackPositionInTicks = userDataObj[emby.constants.PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS]

        if playbackPositionInTicks != itemPlaybackPositionInTicks:
            updateResumePoint = True

    if useUserDataCall:
        updateUserData(embyServer, itemId, playcount, watched, lastPlayed, playbackPositionInTicks)
    else:
        if updateItemPlayed:
            if watched:
                if not markAsWatched(embyServer, itemId, lastPlayed):
                    log('failed to mark item "{}" as watched'.format(item.getLabel()), xbmc.LOGWARNING)
            else:
                if not markAsUnwatched(embyServer, itemId):
                    log('failed to mark item "{}" as unwatched'.format(item.getLabel()), xbmc.LOGWARNING)

        if updateResumePoint:
            if not updateResumePoint(embyServer, itemId, playbackPositionInTicks):
                    log('failed to update resume point for item "{}"'.format(item.getLabel()), xbmc.LOGWARNING)

    xbmcmediaimport.finishUpdateOnProvider(handle)

ACTIONS = {
    # official media import callbacks
    'discoverprovider': discoverProvider,
    'lookupprovider': lookupProvider,
    'canimport': canImport,
    'isproviderready': isProviderReady,
    'isimportready': isImportReady,
    'loadprovidersettings': loadProviderSettings,
    'loadimportsettings': loadImportSettings,
    'canupdatemetadataonprovider': canUpdateMetadataOnProvider,
    'canupdateplaycountonprovider': canUpdatePlaycountOnProvider,
    'canupdatelastplayedonprovider': canUpdateLastPlayedOnProvider,
    'canupdateresumepositiononprovider': canUpdateResumePositionOnProvider,
    'import': execImport,
    'updateonprovider': updateOnProvider,

    # custom setting callbacks
    'testauthentication': testAuthentication,

    # custom setting options fillers
    'settingoptionsfillerusers': settingOptionsFillerUsers,
    'settingoptionsfillerviews': settingOptionsFillerViews
}

if __name__ == '__main__':
    path = sys.argv[0]
    handle = int(sys.argv[1])

    options = None
    if len(sys.argv) > 2:
        # get the options but remove the leading ?
        params = sys.argv[2][1:]
        if params:
            options = urlparse.parse_qs(params)

    log('path = {}, handle = {}, options = {}'.format(path, handle, params), xbmc.LOGDEBUG)

    url = urlparse.urlparse(path)
    action = url.path
    if action[0] == '/':
        action = action[1:]

    if not action in ACTIONS:
        log('cannot process unknown action: {}'.format(action), xbmc.LOGERROR)
        sys.exit(0)

    actionMethod = ACTIONS[action]
    if not actionMethod:
        log('action not implemented: {}'.format(action), xbmc.LOGWARNING)
        sys.exit(0)

    log('executing action "{}"...'.format(action), xbmc.LOGDEBUG)
    actionMethod(handle, options)
