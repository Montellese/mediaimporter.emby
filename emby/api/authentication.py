#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from emby import constants
from emby.request import Request

from lib.utils import Url


class Authentication:
    REQUEST_TIMEOUT_S = 2

    class Method:
        UserId = 0
        Username = 1

    class Result:
        def __init__(self, result=False, accessToken=None, userId=None):
            self.result = result
            self.accessToken = accessToken
            self.userId = userId

    @staticmethod
    # pylint: disable=too-many-arguments
    def Authenticate(baseUrl, authenticationMethod, username=None, userId=None, password=None, deviceId=None):
        if not password:
            raise ValueError('invalid password')

        # prepare the authentication URL
        authUrl = baseUrl
        authUrl = Url.append(authUrl, constants.URL_USERS)

        body = {
            constants.PROPERTY_USER_AUTHENTICATION_PASSWORD: password
        }
        if authenticationMethod == Authentication.Method.UserId:
            if not userId:
                raise ValueError('invalid userId')

            authUrl = Url.append(authUrl, userId, constants.URL_AUTHENTICATE)

        elif authenticationMethod == Authentication.Method.Username:
            if not username:
                raise ValueError('invalid username')

            authUrl = Url.append(authUrl, constants.URL_AUTHENTICATE_BY_NAME)

            body[constants.PROPERTY_USER_AUTHENTICATION_USERNAME] = username

        else:
            raise ValueError('invalid authenticationMethod')

        headers = Request.PrepareApiCallHeaders(deviceId=deviceId, userId=userId)
        headers['Content-Type'] = constants.EMBY_CONTENT_TYPE

        resultObj = Request.PostAsJson(authUrl, headers=headers, json=body, timeout=Authentication.REQUEST_TIMEOUT_S)
        if not resultObj:
            return Authentication.Result()

        if constants.PROPERTY_USER_AUTHENTICATION_ACCESS_TOKEN not in resultObj:
            return Authentication.Result()
        accessToken = \
            resultObj[constants.PROPERTY_USER_AUTHENTICATION_ACCESS_TOKEN]

        if constants.PROPERTY_USER_AUTHENTICATION_USER not in resultObj:
            return Authentication.Result()
        userObj = resultObj[constants.PROPERTY_USER_AUTHENTICATION_USER]
        if constants.PROPERTY_USER_AUTHENTICATION_USER_ID not in userObj:
            return Authentication.Result()

        userId = userObj[constants.PROPERTY_USER_AUTHENTICATION_USER_ID]

        return Authentication.Result(
            result=True,
            accessToken=accessToken,
            userId=userId)
