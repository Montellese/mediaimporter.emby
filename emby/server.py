#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from six.moves.urllib.parse import urlparse, urlunparse

import xbmc

from emby import constants
from emby.authenticator import Authenticator
from emby.request import Request

import lib.semantic_version as semantic_version
from lib.utils import log, splitall, Url

class Server:
    class Info:
        EMBY_SERVER = 'Emby Server'
        JELLYFIN_SERVER = 'Jellyfin Server'

        def __init__(self, id, name, version, product=None):
            if not id:
                raise ValueError('invalid id')

            self.id = id
            self.name = name
            self.version = version
            self.product = product or Server.Info.EMBY_SERVER

        def isEmbyServer(self):
            return self.product == Server.Info.EMBY_SERVER

        def isJellyfinServer(self):
            return self.product == Server.Info.JELLYFIN_SERVER

        def isUnknown(self):
            return not self.isEmbyServer() and not self.isJellyfinServer()

        @staticmethod
        def fromPublicInfo(response):
            if not response or \
               not constants.PROPERTY_SYSTEM_INFO_ID in response or \
               not constants.PROPERTY_SYSTEM_INFO_SERVER_NAME in response or \
               not constants.PROPERTY_SYSTEM_INFO_VERSION in response:
                return None

            versions = response[constants.PROPERTY_SYSTEM_INFO_VERSION].split('.')
            productName = None
            if constants.PROPERTY_SYSTEM_INFO_PRODUCT_NAME in response:
                productName = response[constants.PROPERTY_SYSTEM_INFO_PRODUCT_NAME]

            return Server.Info(
                response[constants.PROPERTY_SYSTEM_INFO_ID],
                response[constants.PROPERTY_SYSTEM_INFO_SERVER_NAME],
                semantic_version.Version('.'.join(versions[0:3])),
                product=productName)

    def __init__(self, provider):
        if not provider:
            raise ValueError('Invalid provider')

        self._baseUrl = provider.getBasePath()
        self._id = provider.getIdentifier()

        settings = provider.getSettings()
        if not settings:
            raise ValueError('Invalid provider without settings')

        self._useHttps = settings.getBool(constants.SETTING_PROVIDER_USE_HTTPS)
        self._verifyHttps = settings.getBool(constants.SETTING_PROVIDER_VERIFY_HTTPS)

        # make sure the base URL uses the proper protocol
        parsedUrl = urlparse(self._baseUrl)
        self._baseUrl = urlunparse(parsedUrl._replace(scheme='https' if self._useHttps else 'http'))

        # prepare the actual URL
        self._url = Url.append(self._baseUrl, constants.EMBY_PROTOCOL)

        self._devideId = settings.getString(constants.SETTING_PROVIDER_DEVICEID)

        userId = settings.getString(constants.SETTING_PROVIDER_USER)
        username = settings.getString(constants.SETTING_PROVIDER_USERNAME)
        password = settings.getString(constants.SETTING_PROVIDER_PASSWORD)
        if userId == constants.SETTING_PROVIDER_USER_OPTION_MANUAL:
            self._authenticator = Authenticator.WithUsername(self._url, self._devideId, username, password, self._verifyHttps)
        else:
            self._authenticator = Authenticator.WithUserId(self._url, self._devideId, userId, password, self._verifyHttps)

    def Authenticate(self):
        return self._authenticator.IsAuthenticated() or self._authenticator.Authenticate()

    def UseHttps(self):
        return self._useHttps

    def VerifyHttps(self):
        return self._verifyHttps

    def Url(self):
        return self._baseUrl

    def DeviceId(self):
        return self._devideId

    def AccessToken(self):
        return self._authenticator.AccessToken()

    def UserId(self):
        return self._authenticator.UserId()

    def ApiGet(self, url):
        if not self._authenticate():
            return False

        return self._get(url)

    def ApiPost(self, url, data={}):
        if not self._authenticate():
            return False

        headers = Request.PrepareApiCallHeaders(authToken=self.AccessToken(), userId=self.UserId(), deviceId=self._devideId)
        return Request.PostAsJson(url, headers=headers, body=data, verifyHttps=self._verifyHttps)

    def ApiDelete(self, url):
        if not self._authenticate():
            return False

        headers = Request.PrepareApiCallHeaders(authToken=self.AccessToken(), userId=self.UserId(), deviceId=self._devideId)
        return Request.Delete(url, headers=headers, verifyHttps=self._verifyHttps)

    def BuildUrl(self, endpoint):
        if not endpoint:
            raise ValueError('Invalid endpoint')

        url = self._url
        return Url.append(url, endpoint)

    def BuildUserUrl(self, endpoint):
        if not endpoint:
            raise ValueError('Invalid endpoint')
        self._assertAuthentication()

        url = self._url
        userId = self.UserId()
        if not userId:
            raise RuntimeError('No valid user authentication available to access endpoint "{}"'.format(endpoint))
        url = Url.append(url, constants.URL_USERS, userId)

        return Url.append(url, endpoint)

    def BuildItemUrl(self, itemId):
        if not itemId:
            raise ValueError('Invalid itemId')

        url = self.BuildUrl(constants.URL_ITEMS)
        return Url.append(url, itemId)

    def BuildUserItemUrl(self, itemId):
        if not itemId:
            raise ValueError('Invalid itemId')

        url = self.BuildUserUrl(constants.URL_ITEMS)
        return Url.append(url, itemId)

    def BuildDirectStreamUrl(self, mediaType, itemId, container):
        if not itemId:
            raise ValueError('Invalid itemId')

        embyMediaType = None
        if mediaType == 'Video':
            embyMediaType = constants.URL_PLAYBACK_MEDIA_TYPE_VIDEO
        elif mediaType == 'Audio':
            embyMediaType = constants.URL_PLAYBACK_MEDIA_TYPE_AUDIO
        else:
            raise ValueError('Invalid mediaType "{}"'.format(mediaType))

        url = self.BuildUrl(embyMediaType)
        url = Url.append(url, itemId, constants.URL_PLAYBACK_STREAM)
        if container:
            containers = container.split(',')
            # TODO(Montellese): for now pick the first container but maybe we
            # need some sanity checking / priorization
            url = '{}.{}'.format(url, containers[0])

        url = Url.addOptions(url, {
            constants.URL_PLAYBACK_OPTION_STATIC: constants.URL_PLAYBACK_OPTION_STATIC_TRUE
        })

        return url

    @staticmethod
    def IsDirectStreamUrl(mediaProvider, url):
        if not mediaProvider:
            raise ValueError('Invalid mediaProvider')
        if not url:
            return False

        parsedBaseUrl = urlparse(mediaProvider.getBasePath())
        parsedUrl = urlparse(url)
        # compare the protocol, hostname and port against the media provider's base URL
        if parsedBaseUrl.scheme != parsedUrl.scheme or \
           parsedBaseUrl.hostname != parsedUrl.hostname or \
           parsedBaseUrl.port != parsedUrl.port:
            return False

        urlPaths = splitall(parsedUrl.path)
        # the first part of the path must be emby
        if urlPaths[1] != constants.EMBY_PROTOCOL:
            return False
        # the second part must either be "Videos" or "Audio"
        if urlPaths[2] not in [ constants.URL_PLAYBACK_MEDIA_TYPE_VIDEO, constants.URL_PLAYBACK_MEDIA_TYPE_AUDIO ]:
            return False
        # the fourth part must start with "stream"
        if not urlPaths[4].startswith(constants.URL_PLAYBACK_STREAM):
            return False

        # the query must be "static=true"
        if parsedUrl.query != '{}={}'.format(constants.URL_PLAYBACK_OPTION_STATIC, constants.URL_PLAYBACK_OPTION_STATIC_TRUE):
            return False

        return True

    def BuildStreamDeliveryUrl(self, deliveryUrl):
        if not deliveryUrl:
            raise ValueError('invalid deliveryUrl')

        return Url.append(self._url, deliveryUrl)

    def BuildSubtitleStreamUrl(self, itemId, sourceId, index, codec):
        if not itemId:
            raise('invalid itemId')
        if not sourceId:
            raise('invalid sourceId')
        if not index:
            raise('invalid index')
        if not codec:
            raise('invalid codec')

        # <url>/Videos/<itemId>/<sourceId>/Subtitles/<index>/Stream.<codec>?api_key=<token>
        url = Url.append(self._url, constants.URL_VIDEOS, itemId, sourceId, constants.URL_VIDEOS_SUBTITLES, str(index), constants.URL_VIDEOS_SUBTITLES_STREAM)
        url = '{}.{}'.format(url, codec)
        return Url.addOptions(url, { constants.URL_QUERY_API_KEY: self._authenticator.AccessToken() })

    def BuildUserPlayingItemUrl(self, itemId):
        if not itemId:
            raise ValueError('Invalid itemId')

        url = self.BuildUserUrl(constants.URL_PLAYING_ITEMS)
        return Url.append(url, itemId)

    def BuildUserPlayedItemUrl(self, itemId):
        if not itemId:
            raise ValueError('Invalid itemId')

        url = self.BuildUserUrl(constants.URL_PLAYED_ITEMS)
        return Url.append(url, itemId)

    def BuildUserItemUserDataUrl(self, itemId):
        if not itemId:
            raise ValueError('Invalid itemId')

        url = self.BuildUserUrl(constants.URL_ITEMS)
        return Url.append(url, itemId, constants.URL_USER_DATA)

    def BuildFolderItemUrl(self, itemId):
        return self.BuildUserItemUrl(itemId)

    def BuildImageUrl(self, itemId, imageType, imageTag = ''):
        if not itemId:
            raise ValueError('Invalid itemId')
        if not imageType:
            raise ValueError('Invalid imageType')

        url = self.BuildItemUrl(itemId)
        url = Url.append(url, constants.URL_IMAGES, imageType)
        if imageTag:
            url = Url.addOptions(url, { constants.URL_QUERY_TAG: imageTag })

        return url

    def BuildSessionsPlayingUrl(self):
        url = self._url
        return Url.append(url, constants.URL_SESSIONS, constants.URL_SESSIONS_PLAYING)

    def BuildSessionsPlayingProgressUrl(self):
        url = self.BuildSessionsPlayingUrl()
        return Url.append(url, constants.URL_SESSIONS_PLAYING_PROGRESS)

    def BuildSessionsPlayingStoppedUrl(self):
        url = self.BuildSessionsPlayingUrl()
        return Url.append(url, constants.URL_SESSIONS_PLAYING_STOPPED)

    @staticmethod
    def BuildProviderId(serverId):
        if not serverId:
            raise ValueError('Invalid serverId')

        return '{}://{}/'.format(constants.EMBY_PROTOCOL, serverId)

    @staticmethod
    def BuildPublicInfoUrl(baseUrl):
        if not baseUrl:
            raise ValueError('Invalid baseUrl')

        return Url.append(baseUrl, constants.EMBY_PROTOCOL, constants.URL_SYSTEM, constants.URL_SYSTEM_INFO, constants.URL_SYSTEM_INFO_PUBLIC)

    @staticmethod
    def BuildIconUrl(baseUrl):
        if not baseUrl:
            raise ValueError('Invalid baseUrl')

        return Url.append(baseUrl, 'web', 'touchicon144.png')

    @staticmethod
    def GetServerInfo(baseUrl):
        publicInfoUrl = Server.BuildPublicInfoUrl(baseUrl)
        headers = Request.PrepareApiCallHeaders()
        resultObj = Request.GetAsJson(publicInfoUrl, headers=headers, verifyHttps=False)  # TODO(Montellese): verify HTTPS?

        return Server.Info.fromPublicInfo(resultObj)

    def _get(self, url):
        headers = Request.PrepareApiCallHeaders(authToken=self.AccessToken(), userId=self.UserId(), deviceId=self._devideId)
        return Request.GetAsJson(url, headers=headers, verifyHttps=self._verifyHttps)

    def _authenticate(self):
        if not self.Authenticate():
            log('user authentication failed on media provider {}'.format(self._id))
            return False

        return True

    def _assertAuthentication(self):
        if not self._authenticator.IsAuthenticated():
            raise RuntimeError('media provider {} has not yet been authenticated'.format(self._id))
