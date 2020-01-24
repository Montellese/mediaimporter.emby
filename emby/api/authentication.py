#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json

from emby import constants
from emby.request import Request

from lib.utils import  Url

class Authentication:
    REQUEST_TIMEOUT_S = 2

    class Method:
        UserId = 0
        Username = 1

    @staticmethod
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
        content = json.dumps(body)

        resultObj = Request.PostAsJson(authUrl, headers=headers, body=content, timeout=Authentication.REQUEST_TIMEOUT_S)
        if not resultObj:
            return (False, None, None)

        if not constants.PROPERTY_USER_AUTHENTICATION_ACCESS_TOKEN in resultObj:
            return (False, None, None)
        accessToken = resultObj[constants.PROPERTY_USER_AUTHENTICATION_ACCESS_TOKEN]

        if not constants.PROPERTY_USER_AUTHENTICATION_USER in resultObj:
            return (False, None, None)
        userObj = resultObj[constants.PROPERTY_USER_AUTHENTICATION_USER]
        if not constants.PROPERTY_USER_AUTHENTICATION_USER_ID in userObj:
            return (False, None, None)

        userId = userObj[constants.PROPERTY_USER_AUTHENTICATION_USER_ID]

        return (True, accessToken, userId)
