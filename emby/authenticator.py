#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from emby.api.authentication import Authentication
from emby.api.embyconnect import EmbyConnect


class AuthenticatorFactory:
    @staticmethod
    def WithUserId(url, deviceId, userId, password='', token=''):  # nosec
        return UserIdAuthenticator(url, deviceId=deviceId, userId=userId, password=password, token=token)

    @staticmethod
    # pylint: disable=too-many-arguments
    def WithUsername(url, deviceId, username, userId, password='', token=''):  # nosec
        return UsernameAuthenticator(url, deviceId=deviceId, username=username, userId=userId, password=password,
                                     token=token)

    @staticmethod
    # pylint: disable=too-many-arguments
    def WithEmbyConnect(url, deviceId, embyConnectUserId, accessKey, userId, token=''):  # nosec
        return EmbyConnectAuthenticator(url, deviceId=deviceId, embyConnectUserId=embyConnectUserId,
                                        accessKey=accessKey, userId=userId, token=token)


class BaseAuthenticator:
    def __init__(self, url, deviceId='', token=''):  # nosec
        if not url:
            raise ValueError('invalid url')

        self._url = url
        self._deviceId = deviceId
        self._accessToken = token or str()
        self._userId = None

    def Authenticate(self, force=False):
        if not force and self.IsAuthenticated():
            return True

        authResult = self._authenticate()

        if not authResult.result or \
           not authResult.accessToken or \
           not authResult.userId:
            return False

        self._userId = authResult.userId
        self._accessToken = authResult.accessToken

        return self.IsAuthenticated()

    def IsAuthenticated(self):
        if not self._accessToken:
            return False

        return True

    def AccessToken(self):
        return self._accessToken

    def UserId(self):
        return self._userId

    def _authenticate(self):
        raise NotImplementedError()


class UsernameAuthenticator(BaseAuthenticator):
    # pylint: disable=too-many-arguments
    def __init__(self, url, deviceId='', username='', userId='', password='', token=''):  # nosec
        super(UsernameAuthenticator, self).__init__(url, deviceId=deviceId, token=token)

        if not username:
            raise ValueError('invalid username')

        self._username = username
        self._userId = userId
        self._password = password

    def _authenticate(self):
        return Authentication.Authenticate(
            self._url,
            Authentication.Method.Username,
            username=self._username,
            password=self._password,
            deviceId=self._deviceId)


class UserIdAuthenticator(BaseAuthenticator):
    # pylint: disable=too-many-arguments
    def __init__(self, url, deviceId='', userId='', password='', token=''):  # nosec
        super(UserIdAuthenticator, self).__init__(url, deviceId=deviceId, token=token)

        if not userId:
            raise ValueError('invalid userId')

        self._userId = userId
        self._password = password

    def _authenticate(self):
        return Authentication.Authenticate(
            self._url,
            Authentication.Method.UserId,
            userId=self._userId,
            password=self._password,
            deviceId=self._deviceId)


class EmbyConnectAuthenticator(BaseAuthenticator):
    # pylint: disable=too-many-arguments
    def __init__(self, url, deviceId='', embyConnectUserId='', accessKey='', userId='', token=''):  # nosec
        super(EmbyConnectAuthenticator, self).__init__(url, deviceId=deviceId, token=token)

        if not embyConnectUserId:
            raise ValueError('invalid embyConnectUserId')
        if not accessKey:
            raise ValueError('invalid accessKey')

        self._embyConnectUserId = embyConnectUserId
        self._userId = userId
        self._accessKey = accessKey

    def _authenticate(self):
        authResult = EmbyConnect.Exchange(
            self._url,
            self._accessKey,
            self._embyConnectUserId,
            deviceId=self._deviceId)

        if not authResult or \
           not authResult.accessToken or \
           not authResult.userId:
            return Authentication.Result()

        return Authentication.Result(
            result=True,
            accessToken=authResult.accessToken,
            userId=authResult.userId)
