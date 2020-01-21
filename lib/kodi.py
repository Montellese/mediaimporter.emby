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
import os
from six import iteritems
from six.moves.urllib.request import urlretrieve
from six.moves.urllib.parse import urlencode, urlparse, urlunparse
import urllib

import xbmc
from xbmcgui import ListItem
import xbmcmediaimport
import xbmcvfs

from emby.api.library import Library
from emby.constants import *
from emby.server import Server

from lib.utils import __addon__, log, mediaProvider2str, Url

# mapping of Kodi and Emby media types
EMBY_MEDIATYPE_BOXSET = 'BoxSet'
EMBY_MEDIATYPES = [
    (xbmcmediaimport.MediaTypeMovie, 'Movie', 32002),
    (xbmcmediaimport.MediaTypeVideoCollection, EMBY_MEDIATYPE_BOXSET, 32007),
    (xbmcmediaimport.MediaTypeTvShow, 'Series', 32003),
    (xbmcmediaimport.MediaTypeSeason, 'Season', 32004),
    (xbmcmediaimport.MediaTypeEpisode, 'Episode', 32005),
    (xbmcmediaimport.MediaTypeMusicVideo, 'MusicVideo', 32006)
]

class Api:
    @staticmethod
    def compareMediaProviders(lhs, rhs):
        if not lhs or not rhs:
            return False

        if lhs.getIdentifier() != rhs.getIdentifier():
            return False

        if lhs.getBasePath() != rhs.getBasePath():
            return False

        if lhs.getFriendlyName() != rhs.getFriendlyName():
            return False

        lhsSettings = lhs.prepareSettings()
        if not lhsSettings:
            return False

        rhsSettings = rhs.prepareSettings()
        if not rhsSettings:
            return False

        if lhsSettings.getString(SETTING_PROVIDER_DEVICEID) != rhsSettings.getString(SETTING_PROVIDER_DEVICEID):
            return False

        lhsSettingsUser = lhsSettings.getString(SETTING_PROVIDER_USER)
        if lhsSettingsUser != rhsSettings.getString(SETTING_PROVIDER_USER):
            return False

        if lhsSettingsUser == SETTING_PROVIDER_USER_OPTION_MANUAL:
            if lhsSettings.getString(SETTING_PROVIDER_USERNAME) != rhsSettings.getString(SETTING_PROVIDER_USERNAME):
                return False

        if lhsSettings.getString(SETTING_PROVIDER_PASSWORD) != rhsSettings.getString(SETTING_PROVIDER_PASSWORD):
            return False

        return True

    @staticmethod
    def getEmbyMediaType(mediaType):
        if not mediaType:
            raise ValueError('invalid mediaType')

        mappedMediaType = [ x for x in EMBY_MEDIATYPES if x[0] == mediaType ]
        if not mappedMediaType:
            return None

        return mappedMediaType[0]

    @staticmethod
    def getKodiMediaType(embyMediaType):
        if not embyMediaType:
            raise ValueError('invalid embyMediaType')

        mappedMediaType = [ x for x in EMBY_MEDIATYPES if x[1] == embyMediaType ]
        if not mappedMediaType:
            return None

        return mappedMediaType[0]

    # one tick is 0.1 microseconds
    TICK_TO_SECONDS_FACTOR = 10000000

    @staticmethod
    def ticksToSeconds(ticks):
        if not ticks:
            return 0

        return ticks / Api.TICK_TO_SECONDS_FACTOR

    @staticmethod
    def secondsToTicks(seconds):
        if not seconds:
            return 0

        return int(seconds * Api.TICK_TO_SECONDS_FACTOR)

    @staticmethod
    def convertDateTimeToDbDateTime(dateTimeStr):
        if not dateTimeStr:
            return ''

        dateTime = parser.parse(dateTimeStr)
        try:
            return dateTime.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            return ''

    @staticmethod
    def getEmbyItemIdFromItem(localItem):
        if not localItem:
            raise ValueError('invalid localItem')

        videoInfoTag = localItem.getVideoInfoTag()
        if not videoInfoTag:
            return None

        return Api.getEmbyItemIdFromVideoInfoTag(videoInfoTag)

    @staticmethod
    def getEmbyItemIdFromVideoInfoTag(videoInfoTag):
        if not videoInfoTag:
            raise ValueError('invalid videoInfoTag')

        embyItemId = videoInfoTag.getUniqueID(EMBY_PROTOCOL)
        if not embyItemId:
            return None

        return embyItemId

    @staticmethod
    def matchImportedItemIdsToLocalItems(localItems, *importedItemIdLists):
        matchedItemLists = []
        itemIdsToProcessLists = []
        for importedItemIds in importedItemIdLists:
            matchedItemLists.append([])
            itemIdsToProcessLists.append(importedItemIds.copy())

        for localItem in localItems:
            # abort if there are no more items to process
            if all(len (itemIdsToProcess) == 0 for itemIdsToProcess in itemIdsToProcessLists):
                break

            # retrieve the local item's Emby ID
            localItemId = Api.getEmbyItemIdFromItem(localItem)
            if not localItemId:
                continue

            # check if it matches one of the imported item IDs
            for index, importedItemIds in enumerate(importedItemIdLists):
                if not localItemId in itemIdsToProcessLists[index]:
                    continue

                matchedItemLists[index].append(localItem)
                itemIdsToProcessLists[index].remove(localItemId)

        return tuple(matchedItemLists)

    @staticmethod
    def toFileItem(embyServer, itemObj, mediaType='', embyMediaType='', libraryView='', allowDirectPlay=True):
        # determine the matching Emby media type if possible
        checkMediaType = len(mediaType) > 0
        if checkMediaType and not embyMediaType:
            mappedMediaType = Api.getEmbyMediaType(mediaType)
            if not mappedMediaType:
                log('cannot import unsupported media type "{}"'.format(mediaType), xbmc.LOGERROR)
                return None

            embyMediaType = mappedMediaType[1]

        if not PROPERTY_ITEM_TYPE in itemObj or (checkMediaType and itemObj.get(PROPERTY_ITEM_TYPE) != embyMediaType):
            log('cannot import {} item from invalid object: {}'.format(mediaType, json.dumps(itemObj)), xbmc.LOGERROR)
            return None

        # determine the Kodi media type based on the Emby media type
        if not checkMediaType:
            embyMediaType = itemObj.get(PROPERTY_ITEM_TYPE)
            mappedMediaType = Api.getKodiMediaType(embyMediaType)
            if not mappedMediaType:
                log('cannot import unsupported Emby media type "{}"'.format(embyMediaType), xbmc.LOGERROR)
                return None

            mediaType = mappedMediaType[0]

        itemId = itemObj.get(PROPERTY_ITEM_ID)
        if not itemId:
            log('cannot import {} item without identifier'.format(mediaType), xbmc.LOGERROR)
            return None

        itemPath = Api.getPlaybackUrl(embyServer, itemId, itemObj, allowDirectPlay=allowDirectPlay)
        if not itemPath:
            return None

        item = ListItem(
            path = itemPath,
            label = itemObj.get(PROPERTY_ITEM_NAME))
        item.setIsFolder(itemObj.get(PROPERTY_ITEM_IS_FOLDER))

        # handle date
        premiereDate = itemObj.get(PROPERTY_ITEM_PREMIERE_DATE)
        if premiereDate:
            item.setDateTime(premiereDate)

        # fill video details
        Api.fillVideoInfos(embyServer, itemId, itemObj, mediaType, item, \
            libraryView=libraryView, allowDirectPlay=allowDirectPlay)

        # handle artwork
        artwork = Api._mapArtwork(embyServer, itemId, itemObj)
        if artwork:
            item.setArt(artwork)

        return item

    @staticmethod
    def getPlaybackUrl(embyServer, itemId, itemObj, allowDirectPlay=True):
        isFolder = itemObj.get(PROPERTY_ITEM_IS_FOLDER)
        itemPath = None
        if PROPERTY_ITEM_MEDIA_SOURCES in itemObj:
            mediaSources = itemObj.get(PROPERTY_ITEM_MEDIA_SOURCES)
            if len(mediaSources) > 0:
                mediaSource = mediaSources[0]
                if mediaSource:
                    itemPath = mediaSource.get(PROPERTY_ITEM_MEDIA_SOURCES_PATH)
                    protocol = mediaSource.get(PROPERTY_ITEM_MEDIA_SOURCES_PROTOCOL)
                    container = mediaSource.get(PROPERTY_ITEM_MEDIA_SOURCES_CONTAINER)
                    supportsDirectPlay = mediaSource.get(PROPERTY_ITEM_MEDIA_SOURCES_SUPPORTS_DIRECT_PLAY)
                    supportsDirectStream = mediaSource.get(PROPERTY_ITEM_MEDIA_SOURCES_SUPPORTS_DIRECT_STREAM)
                    if not supportsDirectPlay and not supportsDirectStream:
                        log('cannot import item with ID {} because it neither support Direct Play nor Direct Stream'.format(itemId), xbmc.LOGWARNING)
                        return None
                    if not allowDirectPlay and not supportsDirectStream:
                        log('cannot import item with ID {} because it doesn\'t support Direct Stream'.format(itemId), xbmc.LOGWARNING)
                        return None

                    # handle Direct Play for directly accessible or HTTP items
                    if allowDirectPlay and supportsDirectPlay:
                        if protocol == PROPERTY_ITEM_MEDIA_SOURCES_PROTOCOL_HTTP or xbmcvfs.exists(itemPath):
                            return itemPath

                        mappedItemPath = Api._mapPath(itemPath, container=container)
                        if xbmcvfs.exists(mappedItemPath):
                            return mappedItemPath

                    # STRMs require Direct Play
                    if not allowDirectPlay and (container == 'strm' or itemPath.endswith('.strm')):
                        log('cannot import item with ID {} because STRMs require Direct Play'.format(itemId), xbmc.LOGWARNING)
                        return None

                    # let the rest be handled as Direct Stream

        if not itemPath:
            # get the direct path
            itemPath = itemObj.get(PROPERTY_ITEM_PATH)
            if not itemPath:
                if isFolder:
                    return embyServer.BuildItemUrl(itemId)

                log('cannot import item with ID {} because it doesn\'t have a proper path'.format(itemId), xbmc.LOGWARNING)
                return None

        if isFolder:
            # make sure folders have a trailing slash
            itemPath = Url.addTrailingSlash(itemPath)

        # if we can access the direct path we can use Direct Play
        if allowDirectPlay:
            if xbmcvfs.exists(itemPath):
                return itemPath

            mappedItemPath = Api._mapPath(itemPath)
            if xbmcvfs.exists(mappedItemPath):
                return mappedItemPath

        if isFolder:
            return embyServer.BuildItemUrl(itemId)

        # fall back to Direct Stream
        return embyServer.BuildDirectStreamUrl(itemObj.get(PROPERTY_ITEM_MEDIA_TYPE), itemId, itemObj.get(PROPERTY_ITEM_CONTAINER))

    @staticmethod
    def fillVideoInfos(embyServer, itemId, itemObj, mediaType, item, libraryView='', allowDirectPlay=True):
        userdata = {}
        if PROPERTY_ITEM_USER_DATA in itemObj:
            userdata = itemObj[PROPERTY_ITEM_USER_DATA]
        info = {
            'mediatype': mediaType,
            'path': itemObj.get(PROPERTY_ITEM_PATH, ''),
            'filenameandpath': item.getPath(),
            'title': item.getLabel() or '',
            'sorttitle': itemObj.get(PROPERTY_ITEM_SORT_NAME, ''),
            'originaltitle': itemObj.get(PROPERTY_ITEM_ORIGINAL_TITLE, ''),
            'plot': Api._mapOverview(itemObj.get(PROPERTY_ITEM_OVERVIEW, '')),
            'plotoutline': itemObj.get(PROPERTY_ITEM_SHORT_OVERVIEW, ''),
            'dateadded': Api.convertDateTimeToDbDateTime(itemObj.get(PROPERTY_ITEM_DATE_CREATED, '')),
            'year': itemObj.get(PROPERTY_ITEM_PRODUCTION_YEAR, 0),
            'rating': itemObj.get(PROPERTY_ITEM_COMMUNITY_RATING, 0.0),
            'mpaa': Api._mapMpaa(itemObj.get(PROPERTY_ITEM_OFFICIAL_RATING, '')),
            'duration': Api.ticksToSeconds(itemObj.get(PROPERTY_ITEM_RUN_TIME_TICKS, 0)),
            'playcount': userdata.get(PROPERTY_ITEM_USER_DATA_PLAY_COUNT, 0),
            'lastplayed': Api.convertDateTimeToDbDateTime(userdata.get(PROPERTY_ITEM_USER_DATA_LAST_PLAYED_DATE, '')),
            'director': [],
            'writer': [],
            'artist': itemObj.get(PROPERTY_ITEM_ARTISTS, []),
            'album': itemObj.get(PROPERTY_ITEM_ALBUM, ''),
            'genre': itemObj.get(PROPERTY_ITEM_GENRES, []),
            'country': itemObj.get(PROPERTY_ITEM_PRODUCTION_LOCATIONS, []),
            'tag': itemObj.get(PROPERTY_ITEM_TAGS, []),
        }

        # add the library view as a tag
        if libraryView:
            info['tag'].append(libraryView)

        # handle aired / premiered
        date = item.getDateTime()
        if date:
            pos = date.find('T')
            if pos >= 0:
                date = date[:pos]

            if mediaType == xbmcmediaimport.MediaTypeEpisode:
                info['aired'] = date
            else:
                info['premiered'] = date

        # handle trailers
        trailerUrl = Api.getTrailer(embyServer, itemId, itemObj, allowDirectPlay=allowDirectPlay)
        if trailerUrl:
            info['trailer'] = trailerUrl

        # handle taglines
        tagline = ''
        embyTaglines = itemObj.get(PROPERTY_ITEM_TAGLINES, [])
        if embyTaglines:
            tagline = embyTaglines[0]
        info['tagline'] = tagline

        # handle studios
        studios = []
        for studio in itemObj.get(PROPERTY_ITEM_STUDIOS, []):
            studios.append(Api._mapStudio(studio['Name']))
        info['studio'] = studios

        # handle tvshow, season and episode specific properties
        if mediaType == xbmcmediaimport.MediaTypeTvShow:
            info['tvshowtitle'] = item.getLabel()
            info['status'] = itemObj.get(PROPERTY_ITEM_STATUS, '')
        elif mediaType == xbmcmediaimport.MediaTypeSeason or mediaType == xbmcmediaimport.MediaTypeEpisode:
            info['tvshowtitle'] = itemObj.get(PROPERTY_ITEM_SERIES_NAME, '')
            index = itemObj.get(PROPERTY_ITEM_INDEX_NUMBER, 0)
            if mediaType == xbmcmediaimport.MediaTypeSeason:
                info['season'] = index

                # ATTENTION
                # something is wrong with the SortName property for seasons which interfers with Kodi
                # abusing sorttitle for custom season titles
                del info['sorttitle']
            else:
                info['season'] = itemObj.get(PROPERTY_ITEM_PARENT_INDEX_NUMBER, 0)
                info['episode'] = index

        # handle actors / cast
        cast = []
        for index, person in enumerate(itemObj.get(PROPERTY_ITEM_PEOPLE, [])):
            name = person.get(PROPERTY_ITEM_PEOPLE_NAME, '')
            type = person.get(PROPERTY_ITEM_PEOPLE_TYPE, '')
            if type == PROPERTY_ITEM_PEOPLE_TYPE_ACTOR:
                cast.append({
                    'name': name,
                    'role': person.get(PROPERTY_ITEM_PEOPLE_ROLE, ''),
                    'order': index
                })
            elif type == PROPERTY_ITEM_PEOPLE_TYPE_WRITER:
                info['writer'].append(name)
            elif type == PROPERTY_ITEM_PEOPLE_TYPE_DIRECTOR:
                info['director'].append(name)

        item.setInfo('video', info)
        item.setCast(cast)

        # handle unique / provider IDs
        uniqueIds = { key.lower(): value for key, value in iteritems(itemObj.get(PROPERTY_ITEM_PROVIDER_IDS, {})) }
        # add the item's ID as a unique ID belonging to Emby
        uniqueIds[EMBY_PROTOCOL] = itemId
        item.getVideoInfoTag().setUniqueIDs(uniqueIds, EMBY_PROTOCOL)

        # handle critic rating as rotten tomato rating
        if PROPERTY_ITEM_CRITIC_RATING in itemObj:
            criticRating = float(itemObj.get(PROPERTY_ITEM_CRITIC_RATING)) / 10.0
            item.setRating('tomatometerallcritics', criticRating)

        # handle resume point
        resumePoint = {
            'totaltime': info['duration'],
            'resumetime': Api.ticksToSeconds(userdata.get(PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS, 0))
        }
        item.setProperties(resumePoint)

        # stream details
        for stream in itemObj.get(PROPERTY_ITEM_MEDIA_STREAMS, []):
            type = stream.get(PROPERTY_ITEM_MEDIA_STREAM_TYPE, '')
            if type == 'Video':
                item.addStreamInfo('video', Api._mapVideoStream({
                    'codec': stream.get(PROPERTY_ITEM_MEDIA_STREAM_CODEC, ''),
                    'profile': stream.get(PROPERTY_ITEM_MEDIA_STREAM_PROFILE, ''),
                    'language': stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE, ''),
                    'width': stream.get(PROPERTY_ITEM_MEDIA_STREAM_WIDTH, 0),
                    'height': stream.get(PROPERTY_ITEM_MEDIA_STREAM_HEIGHT, 0),
                    'aspect': stream.get(PROPERTY_ITEM_MEDIA_STREAM_ASPECT_RATIO, '0'),
                    'stereomode': stream.get(PROPERTY_ITEM_MEDIA_STREAM_VIDEO_3D_FORMAT, 'mono'),
                    'duration': info['duration']
                    }))
            elif type == 'Audio':
                item.addStreamInfo('audio', Api._mapAudioStream({
                    'codec': stream.get(PROPERTY_ITEM_MEDIA_STREAM_CODEC, ''),
                    'profile': stream.get(PROPERTY_ITEM_MEDIA_STREAM_PROFILE, ''),
                    'language': stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE, ''),
                    'channels': stream.get(PROPERTY_ITEM_MEDIA_STREAM_CHANNELS, 2)
                    }))
            elif type == 'Subtitle':
                item.addStreamInfo('subtitle', {
                    'language': stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE, '')
                    })

    @staticmethod
    def getTrailer(embyServer, itemId, itemObj, allowDirectPlay=True):
        # prefer local trailers if direct play is allowed
        if allowDirectPlay and itemObj.get(PROPERTY_ITEM_LOCAL_TRAILER_COUNT, 0):
            localTrailers = Library.GetLocalTrailers(embyServer, itemId)
            if not localTrailers:
                log('failed to retrieve local trailers for item with ID {}'.format(itemId))
            else:
                localTrailerUrl = Api.getPlaybackUrl(embyServer, itemId, localTrailers[0], allowDirectPlay=allowDirectPlay)
                if localTrailerUrl:
                    return localTrailerUrl

        # otherwise use the first remote trailer
        if PROPERTY_ITEM_REMOTE_TRAILERS in itemObj:
            remoteTrailers = itemObj.get(PROPERTY_ITEM_REMOTE_TRAILERS)
            if remoteTrailers:
                return remoteTrailers[0].get(PROPERTY_ITEM_REMOTE_TRAILERS_URL, None)

        return None

    @staticmethod
    def setCollection(item, collectionName):
        if not item:
            raise ValueError('invalid item')
        if not collectionName:
            raise ValueError('invalid collectionName')

        item.setInfo('video', {
            'set': collectionName
        })

    @staticmethod
    def downloadIcon(mediaProvider):
        if not mediaProvider:
            raise ValueError('invalid mediaProvider')

        try:
            basePath = xbmc.translatePath(__addon__.getAddonInfo('profile')).decode('utf-8')
        except AttributeError:
            basePath = xbmc.translatePath(__addon__.getAddonInfo('profile'))

        # determine the icon's URL on the media provider
        iconUrl = Server.BuildIconUrl(mediaProvider.getBasePath())

        # make sure the addon data directory exists
        if not xbmcvfs.exists(basePath):
            if not Api._makeDir(basePath):
                log('failed to create addon data directory at {}'.format(basePath), xbmc.LOGWARNING)
                return iconUrl

        # generate the icon's local path
        serverId = Server.GetServerId(mediaProvider.getIdentifier())
        iconPath = os.path.join(basePath, '{}.png'.format(serverId))

        # try to download the icon (since Emby's webserver doesn't support HEAD requests)
        try:
            urlretrieve(iconUrl, iconPath)
        except IOError as err:
                log('failed to download icon for {} from {}: {}'.format(mediaProvider2str(mediaProvider), iconUrl, err), xbmc.LOGWARNING)
                return iconUrl

        return iconPath

    @staticmethod
    def _makeDir(path):
        # make sure the path ends with a slash
        path = Url.addTrailingSlash(path)

        path = xbmc.translatePath(path)
        if xbmcvfs.exists(path):
            return True

        try:
            _ = xbmcvfs.mkdirs(path)
        except:
            pass

        if xbmcvfs.exists(path):
            return True

        try:
            os.makedirs(path)
        except:
            pass

        return xbmcvfs.exists(path)

    @staticmethod
    def _mapPath(path, container=None):
        if not path:
            return ''

        # turn UNC paths into Kodi-specific Samba paths
        if path.startswith('\\\\'):
            path = path.replace('\\\\', 'smb://', 1).replace('\\\\', '\\').replace('\\', '/')

        # for DVDs and Blue-Ray try to directly access the main playback item
        if container == 'dvd':
            path = '{}/VIDEO_TS/VIDEO_TS.IFO'.format(path)
        elif container == 'bluray':
            path = '{}/BDMV/index.bdmv'.format(path)

        # get rid of any double backslashes
        path = path.replace('\\\\', '\\')

        # make sure paths are consistent
        if '\\' in path:
            path.replace('/', '\\')

        # Kodi expects protocols in lower case
        pathParts = urlparse(path)
        if pathParts.scheme:
            path = urlunparse(pathParts._replace(scheme=pathParts.scheme.lower()))

        return path

    # map the following studios for Kodi
    MAPPED_STUDIOS = {
        'abc (us)': 'ABC',
        'fox (us)': 'FOX',
        'mtv (us)': 'MTV',
        'showcase (ca)': 'Showcase',
        'wgn america': 'WGN',
        'bravo (us)': 'Bravo',
        'tnt (us)': 'TNT',
        'comedy central': 'Comedy Central (US)'
    }

    @staticmethod
    def _mapStudio(studio):
        if studio in Api.MAPPED_STUDIOS:
            return Api.MAPPED_STUDIOS[studio]

        return studio

    @staticmethod
    def _mapOverview(overview):
        if not overview:
            return ''

        return overview \
            .replace('\n', '[CR]') \
            .replace('\r', '') \
            .replace('<br>', '[CR]')

    @staticmethod
    def _mapMpaa(mpaa):
        if not mpaa:
            return ''

        if mpaa in ('NR', 'UR'):
            return 'Not Rated'

        if 'FSK-' in mpaa:
            mpaa = mpaa.replace('-', ' ')

        return mpaa

    @staticmethod
    def _mapVideoStream(stream, container=None):
        # fix some video codecs
        if 'msmpeg4' in stream['codec']:
            stream['codec'] = 'divx'
        elif 'mpeg4' in stream['codec']:
            if not stream['profile'] or 'simple profile' in stream['profile']:
                stream['codec'] = 'xvid'
        elif 'h264' in stream['codec']:
            if container in ('mp4', 'mov', 'm4v'):
                stream['codec'] = 'avc1'

        # try to calculate the aspect ratio
        try:
            width, height = stream['aspect'].split(':')
            stream['aspect'] = round(float(width) / float(height), 6)
        except (ValueError, ZeroDivisionError):
            if stream['width'] and stream['height']:
                stream['aspect'] = round(float(stream['width']) / float(stream['height']), 6)

        # map stereoscopic modes
        if stream['stereomode'] in ('HalfSideBySide', 'FullSideBySide'):
            stream['stereomode'] = 'left_right'
        elif stream['stereomode'] in ('HalfTopAndBottom', 'FullTopAndBottom'):
            stream['stereomode'] = 'top_bottom'

        return stream

    @staticmethod
    def _mapAudioStream(stream):
        # fix some audio codecs
        if 'dts-hd ma' in stream['profile']:
            stream['codec'] = 'dtshd_ma'
        elif 'dts-hd hra' in stream['profile']:
            stream['codec'] = 'dtshd_hra'

        return stream

    @staticmethod
    def _mapArtwork(embyServer, itemId, itemObj):
        artwork = {}
        images = itemObj.get(PROPERTY_ITEM_IMAGE_TAGS)
        if images:
            Api._mapSingleArtwork(embyServer, artwork, itemId, images, PROPERTY_ITEM_IMAGE_TAGS_PRIMARY, 'poster')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images, PROPERTY_ITEM_IMAGE_TAGS_LOGO, 'clearlogo')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images, PROPERTY_ITEM_IMAGE_TAGS_ART, 'clearart')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images, PROPERTY_ITEM_IMAGE_TAGS_BANNER, 'banner')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images, PROPERTY_ITEM_IMAGE_TAGS_THUMB, 'landscape')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images, PROPERTY_ITEM_IMAGE_TAGS_DISC, 'discart')

        images = itemObj.get(PROPERTY_ITEM_BACKDROP_IMAGE_TAGS)
        if images:
            artwork['fanart'] = embyServer.BuildImageUrl(itemId, 'Backdrop/0', images[0])

        return artwork

    @staticmethod
    def _mapSingleArtwork(embyServer, artwork, itemId, imagesObj, embyArtwork, kodiArtwork):
        if embyArtwork in imagesObj:
            artwork[kodiArtwork] = embyServer.BuildImageUrl(itemId, embyArtwork, imagesObj.get(embyArtwork))
