#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import xbmc

from emby import constants
from emby.authenticator import Authenticator
from emby.request import Request

import lib.semantic_version as semantic_version
from lib.utils import log, Url

class Server:
    def __init__(self, provider):
        if not provider:
            raise ValueError('Invalid provider')

        self._url = provider.getBasePath()
        self._url = Url.append(self._url, constants.EMBY_PROTOCOL)
        self._id = provider.getIdentifier()

        settings = provider.getSettings()
        if not settings:
            raise ValueError('Invalid provider without settings')

        self._devideId = settings.getString(constants.SETTING_PROVIDER_DEVICEID)

        userId = settings.getString(constants.SETTING_PROVIDER_USER)
        username = settings.getString(constants.SETTING_PROVIDER_USERNAME)
        password = settings.getString(constants.SETTING_PROVIDER_PASSWORD)
        if userId == constants.SETTING_PROVIDER_USER_OPTION_MANUAL:
            self._authenticator = Authenticator.WithUsername(self._url, self._devideId, username, password)
        else:
            self._authenticator = Authenticator.WithUserId(self._url, self._devideId, userId, password)

    def Authenticate(self):
        return self._authenticator.IsAuthenticated() or self._authenticator.Authenticate()

    def Url(self):
        return self._url

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
        return Request.PostAsJson(url, headers=headers, body=data)

    def ApiDelete(self, url):
        if not self._authenticate():
            return False

        headers = Request.PrepareApiCallHeaders(authToken=self.AccessToken(), userId=self.UserId(), deviceId=self._devideId)
        return Request.Delete(url, headers=headers)

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

    def BuildPlayableItemUrl(self, mediaType, itemId, container):
        if not itemId:
            raise ValueError('Invalid itemId')

        embyMediaType = None
        if mediaType == 'Video':
            embyMediaType = 'Videos'
        elif mediaType == 'Audio':
            embyMediaType = 'Audio'
        else:
            raise ValueError('Invalid mediaType "{}"'.format(mediaType))

        url = self.BuildUrl(embyMediaType)
        url = Url.append(url, itemId, 'stream')
        if container:
            containers = container.split(',')
            # TODO(Montellese): for now pick the first container but maybe we
            # need some sanity checking / priorization
            url = '{}.{}'.format(url, containers[0])

        url = Url.addOptions(url, {
            'static': 'true'
        })

        return url

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
            url = Url.addOptions(url, { 'tag': imageTag })

        return url

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
        resultObj = Request.GetAsJson(publicInfoUrl, headers=headers)
        if not resultObj or \
           not constants.PROPERTY_SYSTEM_INFO_ID in resultObj or \
           not constants.PROPERTY_SYSTEM_INFO_SERVER_NAME in resultObj or \
           not constants.PROPERTY_SYSTEM_INFO_VERSION in resultObj:
            log('failed to retrieve public system information for Emby server at "{}"'.format(publicInfoUrl), xbmc.LOGWARNING)
            return None

        versions = resultObj[constants.PROPERTY_SYSTEM_INFO_VERSION].split('.')

        return (
            resultObj[constants.PROPERTY_SYSTEM_INFO_ID],
            resultObj[constants.PROPERTY_SYSTEM_INFO_SERVER_NAME],
            semantic_version.Version('.'.join(versions[0:3]))
        )

    def _get(self, url):
        headers = Request.PrepareApiCallHeaders(authToken=self.AccessToken(), userId=self.UserId(), deviceId=self._devideId)
        return Request.GetAsJson(url, headers=headers)

    def _authenticate(self):
        if not self.Authenticate():
            log('user authentication failed on media provider {}'.format(self._id))
            return False

        return True

    def _assertAuthentication(self):
        if not self._authenticator.IsAuthenticated():
            raise RuntimeError('media provider {} has not yet been authenticated'.format(self._id))
