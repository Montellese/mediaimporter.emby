#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import hashlib
import json

from emby import constants
from emby.request import Request
from lib.utils import Url

AUTHENTICATION_REQUEST_TIMEOUT_S = 2

class Authenticator:
    class AuthenticationMethod:
        UserId = 0
        Username = 1

    def __init__(self, url, deviceId='', userId='', username='', password='', verifyHttps=True):
        self._url = url
        self._verifyHttps = verifyHttps
        self._deviceId = deviceId
        self._userId = userId
        self._username = username
        self._password = password
        self._accessToken = str()

        if not self._url:
            raise ValueError('url must not be empty')

        if self._userId:
            self._authMethod = Authenticator.AuthenticationMethod.UserId
        elif self._username:
            self._authMethod = Authenticator.AuthenticationMethod.Username
        else:
            raise ValueError('Either userId or username must not be empty')

    @staticmethod
    def WithUserId(url, deviceId, userId, password='', verifyHttps=True):
        return Authenticator(url, deviceId, userId=userId, password=password, verifyHttps=verifyHttps)

    @staticmethod
    def WithUsername(url, deviceId, username, password='', verifyHttps=True):
        return Authenticator(url, deviceId, username=username, password=password, verifyHttps=verifyHttps)

    def Authenticate(self):
        if self.IsAuthenticated():
            return True

        # prepare the authentication URL
        authUrl = self._url
        authUrl = Url.append(authUrl, constants.URL_USERS)

        body = {
            constants.PROPERTY_USER_AUTHENTICATION_PASSWORD: self._password
        }
        if self._authMethod == Authenticator.AuthenticationMethod.UserId:
            authUrl = Url.append(authUrl, self._userId, constants.URL_AUTHENTICATE)
        elif self._authMethod == Authenticator.AuthenticationMethod.Username:
            authUrl = Url.append(authUrl, constants.URL_AUTHENTICATE_BY_NAME)

            body[constants.PROPERTY_USER_AUTHENTICATION_USERNAME] = self._username
        else:
            return False

        headers = Request.PrepareApiCallHeaders(deviceId=self._deviceId, userId=self._userId)
        headers['Content-Type'] = constants.EMBY_CONTENT_TYPE
        content = json.dumps(body)

        resultObj = Request.PostAsJson(authUrl, headers=headers, body=content, timeout=AUTHENTICATION_REQUEST_TIMEOUT_S, verifyHttps=self._verifyHttps)
        if not resultObj:
            return False

        if not constants.PROPERTY_USER_AUTHENTICATION_ACCESS_TOKEN in resultObj:
            return False
        self._accessToken = resultObj[constants.PROPERTY_USER_AUTHENTICATION_ACCESS_TOKEN]

        if not constants.PROPERTY_USER_AUTHENTICATION_USER in resultObj:
            return False
        userObj = resultObj[constants.PROPERTY_USER_AUTHENTICATION_USER]
        if not constants.PROPERTY_USER_AUTHENTICATION_USER_ID in userObj:
            return False

        self._userId = userObj[constants.PROPERTY_USER_AUTHENTICATION_USER_ID]

        return self.IsAuthenticated()

    def IsAuthenticated(self):
        if not self._accessToken:
            return False

        return True

    def AccessToken(self):
        return self._accessToken

    def UserId(self):
        return self._userId
