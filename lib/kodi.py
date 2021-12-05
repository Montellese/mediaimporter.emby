#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
import os

from dateutil import parser
from six import iteritems
from six.moves.urllib.parse import urlparse, urlunparse

import xbmc  # pylint: disable=import-error
from xbmcgui import ListItem  # pylint: disable=import-error
import xbmcmediaimport  # pylint: disable=import-error
import xbmcvfs  # pylint: disable=import-error

from emby.api.library import Library
from emby import constants

from lib.utils import log, Url

# mapping of Kodi and Emby media types
EMBY_MEDIATYPE_BOXSET = 'BoxSet'
EMBY_MEDIATYPES = [
    # Kodi media type, Emby media type, include mixed, label
    (xbmcmediaimport.MediaTypeMovie, 'Movie', True, 32002),
    (xbmcmediaimport.MediaTypeVideoCollection, EMBY_MEDIATYPE_BOXSET, True, 32007),
    (xbmcmediaimport.MediaTypeTvShow, 'Series', True, 32003),
    (xbmcmediaimport.MediaTypeSeason, 'Season', True, 32004),
    (xbmcmediaimport.MediaTypeEpisode, 'Episode', True, 32005),
    (xbmcmediaimport.MediaTypeMusicVideo, 'MusicVideo', False, 32006)
]


class Api:
    @staticmethod
    # pylint: disable=too-many-return-statements
    def compareMediaProviders(lhs, rhs):
        if not lhs or not rhs:
            return False

        if lhs.getIdentifier() != rhs.getIdentifier():
            return False

        if lhs.getFriendlyName() != rhs.getFriendlyName():
            return False

        lhsSettings = lhs.prepareSettings()
        if not lhsSettings:
            return False

        rhsSettings = rhs.prepareSettings()
        if not rhsSettings:
            return False

        if lhsSettings.getString(constants.SETTING_PROVIDER_DEVICEID) != \
           rhsSettings.getString(constants.SETTING_PROVIDER_DEVICEID):
            return False

        lhsSettingsUser = lhsSettings.getString(constants.SETTING_PROVIDER_USER)
        if lhsSettingsUser != rhsSettings.getString(constants.SETTING_PROVIDER_USER):
            return False

        if lhsSettingsUser == constants.SETTING_PROVIDER_USER_OPTION_MANUAL:
            if lhsSettings.getString(constants.SETTING_PROVIDER_USERNAME) != \
               rhsSettings.getString(constants.SETTING_PROVIDER_USERNAME):
                return False

        if lhsSettings.getString(constants.SETTING_PROVIDER_PASSWORD) != \
           rhsSettings.getString(constants.SETTING_PROVIDER_PASSWORD):
            return False

        return True

    @staticmethod
    def getEmbyMediaType(mediaType):
        if not mediaType:
            raise ValueError('invalid mediaType')

        mappedMediaType = [x for x in EMBY_MEDIATYPES if x[0] == mediaType]
        if not mappedMediaType:
            return None

        return mappedMediaType[0]

    @staticmethod
    def getKodiMediaType(embyMediaType):
        if not embyMediaType:
            raise ValueError('invalid embyMediaType')

        mappedMediaType = [x for x in EMBY_MEDIATYPES if x[1] == embyMediaType]
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
    # pylint: disable=too-many-return-statements
    def getEmbyItemIdFromVideoInfoTag(videoInfoTag):
        if not videoInfoTag:
            raise ValueError('invalid videoInfoTag')

        embyItemId = videoInfoTag.getUniqueID(constants.EMBY_PROTOCOL)
        if embyItemId:
            return embyItemId

        # try to get the database Identifier
        dbId = videoInfoTag.getDbId()
        if not dbId:
            return None

        mediaType = videoInfoTag.getMediaType()
        if mediaType == xbmcmediaimport.MediaTypeMovie:
            method = 'Movie'
        elif mediaType == xbmcmediaimport.MediaTypeTvShow:
            method = 'TVShow'
        elif mediaType == xbmcmediaimport.MediaTypeEpisode:
            method = 'Episode'
        elif mediaType == xbmcmediaimport.MediaTypeMusicVideo:
            method = 'MusicVideo'
        else:
            return None

        # use JSON-RPC to retrieve all unique IDs
        jsonResponse = json.loads(xbmc.executeJSONRPC(json.dumps(
            {
                'jsonrpc': '2.0',
                'method': 'VideoLibrary.Get{}Details'.format(method),
                'params': {
                    '{}id'.format(mediaType): dbId,
                    'properties': ['uniqueid'],
                },
                'id': 0
            })))
        if not jsonResponse or 'result' not in jsonResponse:
            return None

        jsonResult = jsonResponse['result']
        detailsKey = '{}details'.format(mediaType)
        if detailsKey not in jsonResult:
            return None

        jsonDetails = jsonResult[detailsKey]
        if 'uniqueid' not in jsonDetails:
            return None

        jsonUniqueIDs = jsonDetails['uniqueid']
        if constants.EMBY_PROTOCOL not in jsonUniqueIDs:
            return None

        return jsonUniqueIDs[constants.EMBY_PROTOCOL]

    @staticmethod
    def matchImportedItemIdsToLocalItems(localItems, *importedItemIdLists):
        matchedItemLists = []
        itemIdsToProcessLists = []
        for importedItemIds in importedItemIdLists:
            matchedItemLists.append([])
            itemIdsToProcessLists.append(importedItemIds.copy())

        for localItem in localItems:
            # abort if there are no more items to process
            if all(len(itemIdsToProcess) == 0 for itemIdsToProcess in itemIdsToProcessLists):
                break

            # retrieve the local item's Emby ID
            localItemId = Api.getEmbyItemIdFromItem(localItem)
            if not localItemId:
                continue

            # check if it matches one of the imported item IDs
            for index, importedItemIds in enumerate(importedItemIdLists):
                if localItemId not in itemIdsToProcessLists[index]:
                    continue

                matchedItemLists[index].append(localItem)
                itemIdsToProcessLists[index].remove(localItemId)

        return tuple(matchedItemLists)

    @staticmethod
    # pylint: disable=too-many-arguments
    def toFileItem(embyServer, itemObj, mediaType='', embyMediaType='', libraryView='', allowDirectPlay=True):
        # determine the matching Emby media type if possible
        checkMediaType = len(mediaType) > 0
        if checkMediaType and not embyMediaType:
            mappedMediaType = Api.getEmbyMediaType(mediaType)
            if not mappedMediaType:
                log('cannot import unsupported media type "{}"'.format(mediaType), xbmc.LOGERROR)
                return None

            embyMediaType = mappedMediaType[1]

        if constants.PROPERTY_ITEM_TYPE not in itemObj or \
           (checkMediaType and itemObj.get(constants.PROPERTY_ITEM_TYPE) != embyMediaType):
            log('cannot import {} item from invalid object: {}'.format(mediaType, json.dumps(itemObj)), xbmc.LOGERROR)
            return None

        # determine the Kodi media type based on the Emby media type
        if not checkMediaType:
            embyMediaType = itemObj.get(constants.PROPERTY_ITEM_TYPE)
            mappedMediaType = Api.getKodiMediaType(embyMediaType)
            if not mappedMediaType:
                log('cannot import unsupported Emby media type "{}"'.format(embyMediaType), xbmc.LOGERROR)
                return None

            mediaType = mappedMediaType[0]

        itemId = itemObj.get(constants.PROPERTY_ITEM_ID)
        if not itemId:
            log('cannot import {} item without identifier'.format(mediaType), xbmc.LOGERROR)
            return None

        itemPath = Api.getPlaybackUrl(embyServer, itemId, itemObj, allowDirectPlay=allowDirectPlay)
        if not itemPath:
            return None

        # create item with video info
        item = Api.createVideoInfoItemWithVideoSetters(
            embyServer, itemId, itemPath, itemObj, mediaType,
            libraryView=libraryView, allowDirectPlay=allowDirectPlay
            )

        # handle artwork
        artwork = Api._mapArtwork(embyServer, itemId, itemObj, mediaType)
        if artwork:
            item.setArt(artwork)

        return item

    @staticmethod
    # pylint: disable=too-many-return-statements, too-many-branches
    def getPlaybackUrl(embyServer, itemId, itemObj, allowDirectPlay=True):
        isFolder = itemObj.get(constants.PROPERTY_ITEM_IS_FOLDER)
        itemPath = None
        if constants.PROPERTY_ITEM_MEDIA_SOURCES in itemObj:
            mediaSources = itemObj.get(constants.PROPERTY_ITEM_MEDIA_SOURCES)
            if len(mediaSources) > 0:
                mediaSource = mediaSources[0]
                if mediaSource:
                    itemPath = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_PATH)
                    protocol = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_PROTOCOL)
                    container = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_CONTAINER)
                    supportsDirectPlay = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_SUPPORTS_DIRECT_PLAY)
                    supportsDirectStream = \
                        mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_SUPPORTS_DIRECT_STREAM)
                    if not supportsDirectPlay and not supportsDirectStream:
                        log('cannot import item with ID {} because it neither support Direct Play nor Direct Stream'
                            .format(itemId), xbmc.LOGWARNING)
                        return None
                    if not allowDirectPlay and not supportsDirectStream:
                        log('cannot import item with ID {} because it doesn\'t support Direct Stream'.format(itemId),
                            xbmc.LOGWARNING)
                        return None

                    # handle Direct Play for directly accessible or HTTP items
                    if allowDirectPlay and supportsDirectPlay:
                        if protocol == constants.PROPERTY_ITEM_MEDIA_SOURCES_PROTOCOL_HTTP or xbmcvfs.exists(itemPath):
                            return itemPath

                        mappedItemPath = Api._mapPath(itemPath, container=container)
                        if xbmcvfs.exists(mappedItemPath):
                            return mappedItemPath

                    # STRMs require Direct Play
                    if not allowDirectPlay and (container == 'strm' or itemPath.endswith('.strm')):
                        log('cannot import item with ID {} because STRMs require Direct Play'.format(itemId),
                            xbmc.LOGWARNING)
                        return None

                    # let the rest be handled as Direct Stream

        if not itemPath:
            # get the direct path
            itemPath = itemObj.get(constants.PROPERTY_ITEM_PATH)
            if not itemPath:
                if isFolder:
                    return embyServer.BuildItemUrl(itemId)

                log('cannot import item with ID {} because it doesn\'t have a proper path'.format(itemId),
                    xbmc.LOGWARNING)
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
        return embyServer.BuildDirectStreamUrl(itemObj.get(constants.PROPERTY_ITEM_MEDIA_TYPE), itemId)

    @staticmethod
    # pylint: disable=too-many-return-statements
    def getDirectPlayUrl(itemObj):
        if itemObj.get(constants.PROPERTY_ITEM_IS_FOLDER):
            return (False, None)

        itemPath = None
        if constants.PROPERTY_ITEM_MEDIA_SOURCES in itemObj:
            mediaSources = itemObj.get(constants.PROPERTY_ITEM_MEDIA_SOURCES)
            if len(mediaSources) > 0:
                mediaSource = mediaSources[0]
                if mediaSource:
                    supportsDirectPlay = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_SUPPORTS_DIRECT_PLAY)
                    if not supportsDirectPlay:
                        return (False, None)

                    itemPath = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_PATH)
                    protocol = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_PROTOCOL)

                    # handle Direct Play for directly accessible or HTTP items
                    if protocol == constants.PROPERTY_ITEM_MEDIA_SOURCES_PROTOCOL_HTTP or xbmcvfs.exists(itemPath):
                        return (True, itemPath)

                    container = mediaSource.get(constants.PROPERTY_ITEM_MEDIA_SOURCES_CONTAINER)

                    mappedItemPath = Api._mapPath(itemPath, container=container)
                    if xbmcvfs.exists(mappedItemPath):
                        return (True, mappedItemPath)

                    # STRMs require Direct Play
                    if container == 'strm' or itemPath.endswith('.strm'):
                        return (False, None)

        # get the direct path
        itemPath = itemObj.get(constants.PROPERTY_ITEM_PATH)
        if not itemPath:
            return (False, None)

        # if we can access the direct path we can use Direct Play
        if xbmcvfs.exists(itemPath):
            return (True, itemPath)

        mappedItemPath = Api._mapPath(itemPath)
        if xbmcvfs.exists(mappedItemPath):
            return (True, mappedItemPath)

        return (False, None)

    @staticmethod
    def getDirectStreamUrl(embyServer, itemId, itemObj):
        if itemObj.get(constants.PROPERTY_ITEM_IS_FOLDER):
            return (False, None)

        # fall back to Direct Stream
        return (True, embyServer.BuildDirectStreamUrl(itemObj.get(constants.PROPERTY_ITEM_MEDIA_TYPE), itemId))

    @staticmethod
     # noqa # pylint: disable=too-many-arguments, too-many-locals, too-many-branches, too-many-statements, too-many-return-statements
    def createVideoInfoItemWithVideoSetters(embyServer, itemId, itemPath, itemObj, mediaType, libraryView='',
        allowDirectPlay=True):

        item = ListItem(
            path=itemPath,
            label=itemObj.get(constants.PROPERTY_ITEM_NAME, ''),
            offscreen=True)
        item.setIsFolder(itemObj.get(constants.PROPERTY_ITEM_IS_FOLDER, False))

        # handle date
        premiereDate = itemObj.get(constants.PROPERTY_ITEM_PREMIERE_DATE)
        if premiereDate:
            item.setDateTime(premiereDate)

        videoInfoTag = item.getVideoInfoTag()

        userdata = {}
        if constants.PROPERTY_ITEM_USER_DATA in itemObj:
            userdata = itemObj[constants.PROPERTY_ITEM_USER_DATA]

        duration = int(Api.ticksToSeconds(itemObj.get(constants.PROPERTY_ITEM_RUN_TIME_TICKS, 0)))

        videoInfoTag.setMediaType(mediaType)
        videoInfoTag.setPath(itemObj.get(constants.PROPERTY_ITEM_PATH, ''))
        videoInfoTag.setFilenameAndPath(item.getPath())
        videoInfoTag.setTitle(item.getLabel() or '')
        videoInfoTag.setSortTitle(itemObj.get(constants.PROPERTY_ITEM_SORT_NAME, ''))
        videoInfoTag.setOriginalTitle(itemObj.get(constants.PROPERTY_ITEM_ORIGINAL_TITLE, ''))
        videoInfoTag.setPlot(Api._mapOverview(itemObj.get(constants.PROPERTY_ITEM_OVERVIEW, '')))
        videoInfoTag.setPlotOutline(itemObj.get(constants.PROPERTY_ITEM_SHORT_OVERVIEW, ''))
        videoInfoTag.setDateAdded(
            Api.convertDateTimeToDbDateTime(itemObj.get(constants.PROPERTY_ITEM_DATE_CREATED, '')))
        videoInfoTag.setYear(itemObj.get(constants.PROPERTY_ITEM_PRODUCTION_YEAR, 0))
        videoInfoTag.setMpaa(Api._mapMpaa(itemObj.get(constants.PROPERTY_ITEM_OFFICIAL_RATING, '')))
        videoInfoTag.setDuration(duration)
        videoInfoTag.setPlaycount(userdata.get(constants.PROPERTY_ITEM_USER_DATA_PLAY_COUNT, 0)
                                  if userdata.get(constants.PROPERTY_ITEM_USER_DATA_PLAYED, False) else 0)
        videoInfoTag.setLastPlayed(Api.convertDateTimeToDbDateTime(
                userdata.get(constants.PROPERTY_ITEM_USER_DATA_LAST_PLAYED_DATE, '')))
        videoInfoTag.setArtists(itemObj.get(constants.PROPERTY_ITEM_ARTISTS, []))
        videoInfoTag.setAlbum(itemObj.get(constants.PROPERTY_ITEM_ALBUM, ''))
        videoInfoTag.setGenres(itemObj.get(constants.PROPERTY_ITEM_GENRES, []))
        videoInfoTag.setCountries(itemObj.get(constants.PROPERTY_ITEM_PRODUCTION_LOCATIONS, []))

        # process ratings
        if constants.PROPERTY_ITEM_COMMUNITY_RATING in itemObj:
            defaultRating = itemObj.get(constants.PROPERTY_ITEM_COMMUNITY_RATING)
            videoInfoTag.setRating(defaultRating, isDefault=True)
        # handle critic rating as rotten tomato rating
        if constants.PROPERTY_ITEM_CRITIC_RATING in itemObj:
            criticRating = float(itemObj.get(constants.PROPERTY_ITEM_CRITIC_RATING)) / 10.0
            videoInfoTag.setRating(criticRating, type='tomatometerallcritics')

        # handle unique / provider IDs
        uniqueIds = \
            {key.lower(): value for key, value in iteritems(itemObj.get(constants.PROPERTY_ITEM_PROVIDER_IDS, {}))}
        defaultUniqueId = Api._mapDefaultUniqueId(uniqueIds, mediaType)
        # add the item's ID as a unique ID belonging to Emby
        uniqueIds[constants.EMBY_PROTOCOL] = itemId
        videoInfoTag.setUniqueIDs(uniqueIds, defaultUniqueId)

        # process tags
        tags = []
        if constants.PROPERTY_ITEM_TAG_ITEMS in itemObj:
            tags = [
                tag.get(constants.PROPERTY_ITEM_TAG_ITEMS_NAME)
                for tag in itemObj.get(constants.PROPERTY_ITEM_TAG_ITEMS)
                if constants.PROPERTY_ITEM_TAG_ITEMS_NAME in tag
                ]
        # add the library view as a tag
        if libraryView:
            tags.append(libraryView)
        videoInfoTag.setTags(tags)

        # handle aired / premiered
        if premiereDate:
            pos = premiereDate.find('T')
            if pos >= 0:
                premiereDate = premiereDate[:pos]

            if mediaType == xbmcmediaimport.MediaTypeEpisode:
                videoInfoTag.setFirstAired(premiereDate)
            else:
                videoInfoTag.setPremiered(premiereDate)

        # handle trailers
        trailerUrl = Api.getTrailer(embyServer, itemId, itemObj, allowDirectPlay=allowDirectPlay)
        if trailerUrl:
            videoInfoTag.setTrailer(trailerUrl)

        # handle taglines
        embyTaglines = itemObj.get(constants.PROPERTY_ITEM_TAGLINES, [])
        if embyTaglines:
            videoInfoTag.setTagLine(embyTaglines[0])

        # handle studios
        studios = []
        for studio in itemObj.get(constants.PROPERTY_ITEM_STUDIOS, []):
            studios.append(Api._mapStudio(studio['Name']))
        videoInfoTag.setStudios(studios)

        # handle tvshow, season and episode specific properties
        if mediaType == xbmcmediaimport.MediaTypeTvShow:
            videoInfoTag.setTvShowTitle(videoInfoTag.getTitle())
            videoInfoTag.setTvShowStatus(itemObj.get(constants.PROPERTY_ITEM_STATUS, ''))
        elif mediaType in (xbmcmediaimport.MediaTypeSeason, xbmcmediaimport.MediaTypeEpisode):
            videoInfoTag.setTvShowTitle(itemObj.get(constants.PROPERTY_ITEM_SERIES_NAME, ''))
            index = itemObj.get(constants.PROPERTY_ITEM_INDEX_NUMBER, 0)
            if mediaType == xbmcmediaimport.MediaTypeSeason:
                videoInfoTag.setSeason(index)

                # ATTENTION
                # something is wrong with the SortName property for seasons which interfers with Kodi
                # abusing sorttitle for custom season titles
                videoInfoTag.setSortTitle('')
            else:
                videoInfoTag.setSeason(itemObj.get(constants.PROPERTY_ITEM_PARENT_INDEX_NUMBER, 0))
                videoInfoTag.setEpisode(index)

        # handle resume point
        videoInfoTag.setResumePoint(
            Api.ticksToSeconds(userdata.get(constants.PROPERTY_ITEM_USER_DATA_PLAYBACK_POSITION_TICKS, 0)),
            duration
            )

        # handle actors / cast
        cast = []
        writers = []
        directors = []
        for index, person in enumerate(itemObj.get(constants.PROPERTY_ITEM_PEOPLE, [])):
            name = person.get(constants.PROPERTY_ITEM_PEOPLE_NAME, '')
            castType = person.get(constants.PROPERTY_ITEM_PEOPLE_TYPE, '')
            if not name:
                log('ignoring person ({}) with missing name for "{}"'.format(castType, item.getLabel()))
                continue

            if castType == constants.PROPERTY_ITEM_PEOPLE_TYPE_ACTOR:
                role = person.get(constants.PROPERTY_ITEM_PEOPLE_ROLE, '')
                # determine the thumbnail (if available)
                thumbnail = ''
                personId = person.get(constants.PROPERTY_ITEM_PEOPLE_ID, None)
                primaryImageTag = person.get(constants.PROPERTY_ITEM_PEOPLE_PRIMARY_IMAGE_TAG, '')
                if personId and primaryImageTag:
                    thumbnail = \
                        embyServer.BuildImageUrl(personId, constants.PROPERTY_ITEM_IMAGE_TAGS_PRIMARY, primaryImageTag)

                cast.append(xbmc.Actor(name, role, index, thumbnail))
            elif castType == constants.PROPERTY_ITEM_PEOPLE_TYPE_WRITER:
                writers.append(name)
            elif castType == constants.PROPERTY_ITEM_PEOPLE_TYPE_DIRECTOR:
                directors.append(name)

        videoInfoTag.setCast(cast)
        videoInfoTag.setWriters(writers)
        videoInfoTag.setDirectors(directors)

        # stream details
        for stream in itemObj.get(constants.PROPERTY_ITEM_MEDIA_STREAMS, []):
            streamType = stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_TYPE, '')
            if streamType == 'video':
                details = Api._mapVideoStream({
                    'codec': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_CODEC, ''),
                    'profile': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_PROFILE, ''),
                    'language': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE, ''),
                    'width': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_WIDTH, 0),
                    'height': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_HEIGHT, 0),
                    'aspect': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_ASPECT_RATIO, '0'),
                    'stereomode': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_VIDEO_3D_FORMAT, 'mono'),
                    'duration': duration
                    })
                videoInfoTag.addVideoStream(xbmc.VideoStreamDetail(
                    width=details['width'],
                    height=details['height'],
                    aspect=details['aspect'],
                    duration=details['duration'],
                    codec=details['codec'],
                    stereoMode=details['stereomode'],
                    language=details['language'],
                ))
            elif streamType == 'audio':
                details = Api._mapAudioStream({
                    'codec': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_CODEC, ''),
                    'profile': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_PROFILE, ''),
                    'language': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE, ''),
                    'channels': stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_CHANNELS, 2)
                    })
                videoInfoTag.addAudioStream(xbmc.AudioStreamDetail(
                    channels=details['channels'],
                    codec=details['codec'],
                    language=details['language'],
                ))
            elif streamType == 'subtitle':
                videoInfoTag.addSubtitleStream(xbmc.SubtitleStreamDetail(
                    language=stream.get(constants.PROPERTY_ITEM_MEDIA_STREAM_LANGUAGE, ''),
                ))

        return item

    @staticmethod
    def getTrailer(embyServer, itemId, itemObj, allowDirectPlay=True):
        # prefer local trailers if direct play is allowed
        if allowDirectPlay and itemObj.get(constants.PROPERTY_ITEM_LOCAL_TRAILER_COUNT, 0):
            localTrailers = Library.GetLocalTrailers(embyServer, itemId)
            if not localTrailers:
                log('failed to retrieve local trailers for item with ID {}'.format(itemId))
            else:
                localTrailerUrl = Api.getPlaybackUrl(embyServer, itemId, localTrailers[0],
                                                     allowDirectPlay=allowDirectPlay)
                if localTrailerUrl:
                    return localTrailerUrl

        # otherwise use the first remote trailer
        if constants.PROPERTY_ITEM_REMOTE_TRAILERS in itemObj:
            remoteTrailers = itemObj.get(constants.PROPERTY_ITEM_REMOTE_TRAILERS)
            if remoteTrailers:
                remoteTrailerUrl = remoteTrailers[0].get(constants.PROPERTY_ITEM_REMOTE_TRAILERS_URL, None)
                try:
                    remoteTrailerId = remoteTrailerUrl.rsplit('=', 1)[1]
                    return 'plugin://plugin.video.youtube/play/?video_id={}'.format(remoteTrailerId)
                except:
                    return remoteTrailers[0].get(constants.PROPERTY_ITEM_REMOTE_TRAILERS_URL, None)

        return None

    @staticmethod
    def setCollection(item, collectionName):
        if not item:
            raise ValueError('invalid item')
        if not collectionName:
            raise ValueError('invalid collectionName')

        item.getVideoInfoTag().setSet(collectionName)

    @staticmethod
    def _makeDir(path):
        # make sure the path ends with a slash
        path = Url.addTrailingSlash(path)

        path = xbmcvfs.translatePath(path)
        if xbmcvfs.exists(path):
            return True

        try:
            _ = xbmcvfs.mkdirs(path)
        except:  # noqa: E722 # nosec
            pass

        if xbmcvfs.exists(path):
            return True

        try:
            os.makedirs(path)
        except:  # noqa: E722 # nosec
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

    UNIQUE_ID_IMDB = 'imdb'
    UNIQUE_ID_TMDB = 'tmdb'
    UNIQUE_ID_TVDB = 'tvdb'

    @staticmethod
    def _mapDefaultUniqueId(uniqueIds, mediaType):
        if not uniqueIds or not mediaType:
            return ''

        uniqueIdKeys = uniqueIds.keys()

        # for tvshows, seasons and episodes prefer TVDB
        if mediaType in \
           (xbmcmediaimport.MediaTypeTvShow, xbmcmediaimport.MediaTypeSeason, xbmcmediaimport.MediaTypeEpisode):
            if Api.UNIQUE_ID_TVDB in uniqueIdKeys:
                return Api.UNIQUE_ID_TVDB

        # otherwise prefer IMDd over TMDd
        if Api.UNIQUE_ID_IMDB in uniqueIdKeys:
            return Api.UNIQUE_ID_IMDB
        if Api.UNIQUE_ID_TMDB in uniqueIdKeys:
            return Api.UNIQUE_ID_TMDB

        # last but not least fall back to the first key
        return next(iter(uniqueIdKeys))

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
    def _mapArtwork(embyServer, itemId, itemObj, mediaType):
        artwork = {}
        images = itemObj.get(constants.PROPERTY_ITEM_IMAGE_TAGS)
        if images:
            if mediaType in (xbmcmediaimport.MediaTypeEpisode, xbmcmediaimport.MediaTypeMusicVideo):
                Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                      constants.PROPERTY_ITEM_IMAGE_TAGS_PRIMARY, 'thumb')
            else:
                Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                      constants.PROPERTY_ITEM_IMAGE_TAGS_PRIMARY, 'poster')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                  constants.PROPERTY_ITEM_IMAGE_TAGS_LOGO, 'clearlogo')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                  constants.PROPERTY_ITEM_IMAGE_TAGS_ART, 'clearart')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                  constants.PROPERTY_ITEM_IMAGE_TAGS_BANNER, 'banner')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                  constants.PROPERTY_ITEM_IMAGE_TAGS_THUMB, 'landscape')
            Api._mapSingleArtwork(embyServer, artwork, itemId, images,
                                  constants.PROPERTY_ITEM_IMAGE_TAGS_DISC, 'discart')

        images = itemObj.get(constants.PROPERTY_ITEM_BACKDROP_IMAGE_TAGS)
        if images:
            artwork['fanart'] = embyServer.BuildImageUrl(itemId, 'Backdrop/0', images[0])

        return artwork

    @staticmethod
    # pylint: disable=too-many-arguments
    def _mapSingleArtwork(embyServer, artwork, itemId, imagesObj, embyArtwork, kodiArtwork):
        if embyArtwork in imagesObj:
            artwork[kodiArtwork] = embyServer.BuildImageUrl(itemId, embyArtwork, imagesObj.get(embyArtwork))
