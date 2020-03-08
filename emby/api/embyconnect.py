#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import hashlib

import xbmc

from emby import constants, server
from emby.request import Request

from lib.utils import log, Url

class EmbyConnect:
    class AuthenticationResult:
        def __init__(self, accessToken=None, userId=None):
            if not accessToken:
                raise ValueError('invalid accessToken')
            if not userId:
                raise ValueError('invalid userId')

            self.accessToken = accessToken
            self.userId = userId

    class Server:
        def __init__(self, id=None, systemId=None, accessKey=None, name=None, remoteUrl=None, localUrl=None):
            if not id:
                raise ValueError('invalid id')
            if not systemId:
                raise ValueError('invalid systemId')
            if not accessKey:
                raise ValueError('invalid accessKey')
            if not name:
                raise ValueError('invalid name')
            if not remoteUrl and not localUrl:
                raise ValueError('either remoteUrl or localUrl must be provided')

            self.id = id
            self.systemId = systemId
            self.accessKey = accessKey
            self.name = name
            self.remoteUrl = remoteUrl
            self.localUrl = localUrl

    @staticmethod
    def Authenticate(username, password):
        if not username:
            raise ValueError('invalid username')
        if not password:
            raise ValueError('invalid password')

        url = Url.append(constants.URL_EMBY_CONNECT_BASE, constants.URL_EMBY_CONNECT_AUTHENTICATE)
        headers = EmbyConnect._getApplicationHeader()

        body = {
            constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_NAME_OR_EMAIL: username,
            constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_PASSWORD: hashlib.md5(password),
        }

        resultObj = Request.PostAsJson(url, headers=headers, json=body)
        if not resultObj or \
           not constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_ACCESS_TOKEN in resultObj or \
           not constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_USER in resultObj:
            log('invalid response from {}: {}'.format(url, resultObj))
            return None

        userObj = resultObj.get(constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_USER)
        if not constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_USER_ID in userObj:
            log('invalid response from {}: {}'.format(url, resultObj))
            return None

        return EmbyConnect.AuthenticationResult(
            accessToken=resultObj.get(constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_ACCESS_TOKEN),
            userId=userObj.get(constants.PROPERTY_EMBY_CONNECT_AUTHENTICATION_USER_ID)
        )

    @staticmethod
    def GetServers(accessToken, userId):
        if not accessToken:
            raise ValueError('invalid accessToken')
        if not userId:
            raise ValueError('invalid userId')

        url = Url.append(constants.URL_EMBY_CONNECT_BASE, constants.URL_EMBY_CONNECT_SERVERS)
        url = Url.addOptions(url, {
            constants.URL_QUERY_USER_ID: userId,
        })
        headers = EmbyConnect._getApplicationHeader()
        headers.update({
            constants.EMBY_CONNECT_USER_TOKEN_HEADER: accessToken,
        })

        resultObj = Request.GetAsJson(url, headers=headers)
        if not resultObj:
            log('invalid response from {}: {}'.format(url, resultObj))
            return None

        servers = []
        for server in resultObj:
            id = server.get(constants.PROPERTY_EMBY_CONNECT_SERVER_ID, None)
            systemId = server.get(constants.PROPERTY_EMBY_CONNECT_SERVER_SYSTEM_ID, None)
            accessKey = server.get(constants.PROPERTY_EMBY_CONNECT_SERVER_ACCESS_KEY, None)
            name = server.get(constants.PROPERTY_EMBY_CONNECT_SERVER_NAME, None)
            remoteUrl = server.get(constants.PROPERTY_EMBY_CONNECT_SERVER_REMOTE_URL, None)
            localUrl = server.get(constants.PROPERTY_EMBY_CONNECT_SERVER_LOCAL_URL, None)

            if None in (id, accessKey, name, remoteUrl, localUrl):
                log('invalid Emby server received from {}: {}'.format(url, server))
                continue

            servers.append(EmbyConnect.Server(
                id=id,
                systemId=systemId,
                accessKey=accessKey,
                name=name,
                remoteUrl=remoteUrl,
                localUrl=localUrl
            ))

        return servers

    @staticmethod
    def Exchange(baseUrl, accessKey, userId, deviceId=None):
        if not baseUrl:
            raise ValueError('invalid baseUrl')
        if not accessKey:
            raise ValueError('invalid accessKey')
        if not userId:
            raise ValueError('invalid userId')

        exchangeUrl = server.Server.BuildConnectExchangeUrl(baseUrl, userId)
        headers = Request.PrepareApiCallHeaders(deviceId=deviceId)
        headers.update({
            constants.EMBY_CONNECT_TOKEN_HEADER: accessKey,
        })

        resultObj = Request.GetAsJson(exchangeUrl, headers=headers)
        if not resultObj or \
           not constants.PROPERTY_EMBY_CONNECT_EXCHANGE_LOCAL_USER_ID in resultObj or \
           not constants.PROPERTY_EMBY_CONNECT_EXCHANGE_ACCESS_TOKEN in resultObj:
            log('invalid response from {}: {}'.format(exchangeUrl, resultObj))
            return None

        return EmbyConnect.AuthenticationResult(
            accessToken=resultObj.get(constants.PROPERTY_EMBY_CONNECT_EXCHANGE_ACCESS_TOKEN),
            userId=resultObj.get(constants.PROPERTY_EMBY_CONNECT_EXCHANGE_LOCAL_USER_ID)
        )

    @staticmethod
    def _getApplicationHeader():
        return {
            constants.EMBY_APPLICATION_HEADER: '{}/{}'.format(xbmc.getInfoLabel('System.FriendlyName'), xbmc.getInfoLabel('System.BuildVersionShort'))
        }

    class PinLogin:
        def __init__(self, deviceId):
            if not deviceId:
                raise ValueError('invalid deviceId')

            self._authenticationResult = None
            self.finished = False
            self.expired = False
            self.deviceId = deviceId
            self.pin = None

            self.pin = self._getPin()
            if not self.pin:
                raise RuntimeError('failed to get PIN')

        def checkLogin(self):
            if self.finished:
                return not self.expired

            url = Url.append(constants.URL_EMBY_CONNECT_BASE, constants.URL_EMBY_CONNECT_PIN)
            url = Url.addOptions(url, {
                constants.URL_QUERY_DEVICE_ID: self.deviceId,
                constants.URL_QUERY_PIN: self.pin,
            })

            resultObj = Request.GetAsJson(url)
            if not resultObj or \
               not constants.PROPERTY_EMBY_CONNECT_PIN_IS_CONFIRMED in resultObj or \
               not constants.PROPERTY_EMBY_CONNECT_PIN_IS_EXPIRED in resultObj:
                log('failed to check status of PIN {} at {}: {}'.format(self.pin, url, resultObj), xbmc.LOGWARNING)
                self.finished = True
                self.expired = True
                return False

            self.finished = resultObj.get(constants.PROPERTY_EMBY_CONNECT_PIN_IS_CONFIRMED)
            self.expired = resultObj.get(constants.PROPERTY_EMBY_CONNECT_PIN_IS_EXPIRED)
            if self.expired:
                self.finished = True

            return self.finished

        def exchange(self):
            if not self.pin:
                return None

            if not self.finished or self.expired:
                return None

            if self._authenticationResult:
                return self._authenticationResult

            url = Url.append(constants.URL_EMBY_CONNECT_BASE, constants.URL_EMBY_CONNECT_PIN, constants.URL_EMBY_CONNECT_PIN_AUTHENTICATE)
            body = {
                constants.URL_QUERY_DEVICE_ID: self.deviceId,
                constants.URL_QUERY_PIN: self.pin,
            }

            resultObj = Request.PostAsJson(url, json=body)
            if not resultObj or \
               not constants.PROPERTY_EMBY_CONNECT_PIN_USER_ID in resultObj or \
               not constants.PROPERTY_EMBY_CONNECT_PIN_ACCESS_TOKEN in resultObj:
                log('failed to authenticate with PIN {} at {}: {}'.format(self.pin, url, resultObj))
                return None

            self._authenticationResult = EmbyConnect.AuthenticationResult(
                accessToken=resultObj.get(constants.PROPERTY_EMBY_CONNECT_PIN_ACCESS_TOKEN),
                userId=resultObj.get(constants.PROPERTY_EMBY_CONNECT_PIN_USER_ID))
            return self._authenticationResult

        def _getPin(self):
            if self.pin:
                return self.pin

            url = Url.append(constants.URL_EMBY_CONNECT_BASE, constants.URL_EMBY_CONNECT_PIN)
            body = {
                constants.URL_QUERY_DEVICE_ID: self.deviceId
            }

            resultObj = Request.PostAsJson(url, json=body)
            if not resultObj or \
               not constants.PROPERTY_EMBY_CONNECT_PIN in resultObj:
                log('failed to get a PIN from {}: {}'.format(url, resultObj))
                return None

            self.pin = resultObj.get(constants.PROPERTY_EMBY_CONNECT_PIN)

            return self.pin
