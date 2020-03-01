#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from emby.api.authentication import Authentication

from lib.utils import Url

class Authenticator:
    def __init__(self, url, deviceId='', userId='', username='', password='', token=''):
        self._url = url
        self._deviceId = deviceId
        self._userId = userId
        self._username = username
        self._password = password
        self._accessToken = token or str()

        if not self._url:
            raise ValueError('url must not be empty')

        if self._userId:
            self._authMethod = Authentication.Method.UserId
        elif self._username:
            self._authMethod = Authentication.Method.Username
        else:
            raise ValueError('Either userId or username must not be empty')

    @staticmethod
    def WithUserId(url, deviceId, userId, password='', token=''):
        return Authenticator(url, deviceId, userId=userId, password=password, token=token)

    @staticmethod
    def WithUsername(url, deviceId, username, password='', token=''):
        return Authenticator(url, deviceId, username=username, password=password, token=token)

    def Authenticate(self, force=False):
        if not force and self.IsAuthenticated():
            return True

        (result, accessToken, userId) = \
            Authentication.Authenticate(self._url, self._authMethod, \
                username=self._username, userId=self._userId, password=self._password, \
                deviceId=self._deviceId)

        if not result:
            return False

        self._accessToken = accessToken
        self._userId = userId

        return self.IsAuthenticated()

    def IsAuthenticated(self):
        if not self._accessToken:
            return False

        return True

    def AccessToken(self):
        return self._accessToken

    def UserId(self):
        return self._userId
