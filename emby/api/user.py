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

class User:
    def __init__(self, name, identifier):
        self.name = name
        self.id = identifier

    @staticmethod
    def GetPublicUsers(baseUrl, deviceId=None):
        users = []

        usersUrl = Url.append(baseUrl, constants.EMBY_PROTOCOL, constants.URL_USERS, constants.URL_USERS_PUBLIC)
        headers = Request.PrepareApiCallHeaders(deviceId=deviceId)
        resultObj = Request.GetAsJson(usersUrl, headers=headers)
        if not resultObj:
            return users

        for userObj in resultObj:
            # make sure the 'Name' and 'Id' properties are available
            if not constants.PROPERTY_USER_NAME in userObj or not constants.PROPERTY_USER_ID in userObj:
                continue

            # make sure the name and id properties are valid
            user = User(userObj[constants.PROPERTY_USER_NAME], userObj[constants.PROPERTY_USER_ID])
            if not user.name or not user.id:
                continue

            # check if the user is disabled
            if constants.PROPERTY_USER_POLICY in userObj and \
               constants.PROPERTY_USER_IS_DISABLED in userObj[constants.PROPERTY_USER_POLICY] and \
               userObj[constants.PROPERTY_USER_POLICY][constants.PROPERTY_USER_IS_DISABLED]:
                continue

            users.append(user)

        return users
