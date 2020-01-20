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

import xbmc
from xbmcgui import ListItem
import xbmcmediaimport
import xbmcvfs

from emby.constants import *

from lib.utils import log, Url

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
    def prepareUrlForKodi(url, embyServer=None, verifyHttps=True):
        if not url:
            return ''

        if not verifyHttps or (embyServer and not embyServer.VerifyHttps()):
            url = Url.addProtocolOptions(url, { URL_PROTOCOL_VERIFY_PEER: 'false' })

        return url

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

        itemPath = None
        isFolder = itemObj.get(PROPERTY_ITEM_IS_FOLDER)
        if isFolder:
            itemPath = Api.prepareUrlForKodi(embyServer.BuildItemUrl(itemId), embyServer=embyServer)
        else:
            if allowDirectPlay:
                # get the direct path
                path = itemObj.get(PROPERTY_ITEM_PATH)
                # if we can access the direct path we can use Direct Play otherwise we use Direct Stream
                if path and xbmcvfs.exists(path):
                    itemPath = path

            # fall back to Direct Stream
            if not itemPath:
                itemPath = Api.prepareUrlForKodi( \
                    embyServer.BuildDirectStreamUrl(itemObj.get(PROPERTY_ITEM_MEDIA_TYPE), itemId, itemObj.get(PROPERTY_ITEM_CONTAINER)), \
                    embyServer=embyServer)

        item = ListItem(
            path = itemPath,
            label = itemObj.get(PROPERTY_ITEM_NAME))
        item.setIsFolder(isFolder)

        # handle date
        premiereDate = itemObj.get(PROPERTY_ITEM_PREMIERE_DATE)
        if premiereDate:
            item.setDateTime(premiereDate)

        # fill video details
        Api.fillVideoInfos(itemId, itemObj, mediaType, item, libraryView=libraryView)

        # handle artwork
        artwork = Api._mapArtwork(embyServer, itemId, itemObj)
        if artwork:
            item.setArt(artwork)

        return item

    @staticmethod
    def fillVideoInfos(itemId, itemObj, mediaType, item, libraryView=''):
        userdata = {}
        if PROPERTY_ITEM_USER_DATA in itemObj:
            userdata = itemObj[PROPERTY_ITEM_USER_DATA]
        info = {
            'mediatype': mediaType,
            'path': itemObj.get(PROPERTY_ITEM_PATH) or '',
            'filenameandpath': item.getPath(),
            'title': item.getLabel() or '',
            'sorttitle': itemObj.get(PROPERTY_ITEM_SORT_NAME) or '',
            'originaltitle': itemObj.get(PROPERTY_ITEM_ORIGINAL_TITLE) or '',
            'plot': itemObj.get(PROPERTY_ITEM_OVERVIEW) or '',
            'plotoutline': itemObj.get(PROPERTY_ITEM_SHORT_OVERVIEW) or '',
            'dateadded': Api.convertDateTimeToDbDateTime(itemObj.get(PROPERTY_ITEM_DATE_CREATED) or ''),
            'year': itemObj.get(PROPERTY_ITEM_PRODUCTION_YEAR) or 0,
            'rating': itemObj.get(PROPERTY_ITEM_COMMUNITY_RATING) or 0.0,
            'mpaa': itemObj.get(PROPERTY_ITEM_OFFICIAL_RATING) or '',
            'duration': Api.ticksToSeconds(itemObj.get(PROPERTY_ITEM_RUN_TIME_TICKS)),
            'playcount': userdata.get(PROPERTY_ITEM_USER_DATA_PLAY_COUNT) or 0,
            'lastplayed': Api.convertDateTimeToDbDateTime(userdata.get(PROPERTY_ITEM_USER_DATA_LAST_PLAYED_DATE) or ''),
            'director': [],
            'writer': [],
            'artist': itemObj.get(PROPERTY_ITEM_ARTISTS) or [],
            'album': itemObj.get(PROPERTY_ITEM_ALBUM) or '',
            'genre': itemObj.get(PROPERTY_ITEM_GENRES) or [],
            'country': itemObj.get(PROPERTY_ITEM_PRODUCTION_LOCATIONS) or [],
            'tag': itemObj.get(PROPERTY_ITEM_TAGS) or []
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

        # handle taglines
        tagline = ''
        embyTaglines = itemObj.get(PROPERTY_ITEM_TAGLINES)
        if embyTaglines:
            tagline = embyTaglines[0]
        info['tagline'] = tagline

        # handle studios
        studios = []
        embyStudios = itemObj.get(PROPERTY_ITEM_STUDIOS)
        if embyStudios:
            for studio in embyStudios:
                studios.append(studio['Name'])
        info['studio'] = studios

        # handle tvshow, season and episode specific properties
        if mediaType == xbmcmediaimport.MediaTypeTvShow:
            info['tvshowtitle'] = item.getLabel()
            info['status'] = itemObj.get(PROPERTY_ITEM_STATUS) or ''
        elif mediaType == xbmcmediaimport.MediaTypeSeason or mediaType == xbmcmediaimport.MediaTypeEpisode:
            info['tvshowtitle'] = itemObj.get(PROPERTY_ITEM_SERIES_NAME) or ''
            index = itemObj.get(PROPERTY_ITEM_INDEX_NUMBER) or 0
            if mediaType == xbmcmediaimport.MediaTypeSeason:
                info['season'] = index

                # ATTENTION
                # something is wrong with the SortName property for seasons which interfers with Kodi
                # abusing sorttitle for custom season titles
                del info['sorttitle']
            else:
                info['season'] = itemObj.get(PROPERTY_ITEM_PARENT_INDEX_NUMBER) or 0
                info['episode'] = index

        # handle actors / cast
        cast = []
        people = itemObj.get(PROPERTY_ITEM_PEOPLE)
        if people:
            for index, person in enumerate(people):
                name = person.get(PROPERTY_ITEM_PEOPLE_NAME)
                type = person.get(PROPERTY_ITEM_PEOPLE_TYPE)
                if type == PROPERTY_ITEM_PEOPLE_TYPE_ACTOR:
                    cast.append({
                        'name': name,
                        'role': person.get(PROPERTY_ITEM_PEOPLE_ROLE),
                        'order': index
                    })
                elif type == PROPERTY_ITEM_PEOPLE_TYPE_WRITER:
                    info['writer'].append(name)
                elif type == PROPERTY_ITEM_PEOPLE_TYPE_DIRECTOR:
                    info['director'].append(name)

        item.setInfo('video', info)
        item.setCast(cast)

        # handle unique / provider IDs
        uniqueIds = itemObj.get(PROPERTY_ITEM_PROVIDER_IDS) or {}
        # add the item's ID as a unique ID belonging to Emby
        uniqueIds[EMBY_PROTOCOL] = itemId
        item.getVideoInfoTag().setUniqueIDs(uniqueIds, EMBY_PROTOCOL)

        # handle resume point
        resumePoint = {
            'totaltime': info['duration'],
            'resumetime': Api.ticksToSeconds(userdata.get(PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS))
        }
        item.setProperties(resumePoint)

        # stream details
        mediaStreams = itemObj.get(PROPERTY_ITEM_MEDIA_STREAMS)
        if mediaStreams:
            for stream in mediaStreams:
                type = stream.get(PROPERTY_ITEM_MEDIA_STREAM_TYPE)
                if type == 'Video':
                    item.addStreamInfo('video', {
                        'codec': stream.get(PROPERTY_ITEM_MEDIA_STREAM_CODEC),
                        'language': stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE),
                        'width': stream.get(PROPERTY_ITEM_MEDIA_STREAM_WIDTH),
                        'height': stream.get(PROPERTY_ITEM_MEDIA_STREAM_HEIGHT),
                        'duration': info['duration']
                        })
                elif type == 'Audio':
                    item.addStreamInfo('audio', {
                        'codec': stream.get(PROPERTY_ITEM_MEDIA_STREAM_CODEC),
                        'language': stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE),
                        'channels': stream.get(PROPERTY_ITEM_MEDIA_STREAM_CHANNELS)
                        })
                elif type == 'Subtitle':
                    item.addStreamInfo('subtitle', {
                        'language': stream.get(PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE)
                        })

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
            artwork['fanart'] = Api.prepareUrlForKodi( \
                embyServer.BuildImageUrl(itemId, 'Backdrop/0', images[0]), \
                embyServer=embyServer)

        return artwork

    @staticmethod
    def _mapSingleArtwork(embyServer, artwork, itemId, imagesObj, embyArtwork, kodiArtwork):
        if embyArtwork in imagesObj:
            artwork[kodiArtwork] = Api.prepareUrlForKodi( \
                embyServer.BuildImageUrl(itemId, embyArtwork, imagesObj.get(embyArtwork)), \
                embyServer=embyServer)
