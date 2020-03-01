#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import json
import requests
import uuid

import xbmc

from emby import constants

from lib.utils import log

# set this to True to get debug logs for calls to the Emby API
EMBY_API_DEBUG_ENABLED = True  # TODO(Montellese)

class NotAuthenticatedError(Exception):
    pass

class Request:
    _initialized = False
    _device = 'Kodi'
    _version = ''

    @staticmethod
    def PrepareApiCallHeaders(authToken='', deviceId='', userId=''):
        if not Request._initialized:
            Request._device = xbmc.getInfoLabel('System.FriendlyName')
            Request._version = xbmc.getInfoLabel('System.BuildVersionShort')
            Request._initialized = True

        headers = {
            'Accept': constants.EMBY_CONTENT_TYPE
        }

        if authToken:
            headers[constants.EMBY_API_KEY_HEADER] = authToken

        if not deviceId:
            deviceId = str(uuid.uuid4())

        embyAuthorizationHeader = \
            'MediaBrowser Client="{}", Device="{}", DeviceId="{}", Version="{}"'.format( \
                'Kodi', Request._device, deviceId, Request._version)
        if userId:
            embyAuthorizationHeader += ', UserId="{}"'.format(userId)
        headers[constants.EMBY_AUTHORIZATION_HEADER] = embyAuthorizationHeader

        return headers

    @staticmethod
    def Get(url, headers={}, timeout=None):
        result = Request._get(url, headers=headers, timeout=timeout)
        return Request._handleRequestAsContent(result, 'GET')

    @staticmethod
    def GetAsJson(url, headers={}, timeout=None):
        result = Request._get(url, headers=headers, timeout=timeout)
        return Request._handleRequestAsJson(result, 'GET')

    @staticmethod
    def Post(url, headers={}, body=None, json=None, timeout=None):
        result = Request._post(url, headers=headers, body=body, json=json, timeout=timeout)
        return Request._handleRequestAsContent(result, 'POST')

    @staticmethod
    def PostAsJson(url, headers={}, body=None, json=None, timeout=None):
        result = Request._post(url, headers=headers, body=body, json=json, timeout=timeout)
        return Request._handleRequestAsJson(result, 'POST')

    @staticmethod
    def Delete(url, headers={}, timeout=None):
        result = Request._delete(url, headers=headers, timeout=timeout)
        return Request._handleRequestAsContent(result, 'DELETE')

    @staticmethod
    def DeleteAsJson(url, headers={}, timeout=None):
        result = Request._delete(url, headers=headers, timeout=timeout)
        return Request._handleRequestAsJson(result, 'DELETE')

    @staticmethod
    def _get(url, headers={}, timeout=None):
        Request._logRequest('GET', url, headers)
        try:
            return requests.get(url, headers=headers, timeout=timeout, verify=False)
        except requests.exceptions.RequestException as err:
            log('error retrieving response from GET {}: {}'.format(url, err.message), xbmc.LOGERROR)

        return None

    @staticmethod
    def _post(url, headers={}, body=None, json=None, timeout=None):
        if body and json:
            raise ValueError('body and json can\'t be combined')

        Request._logRequest('POST', url, headers, body or json)
        try:
            return requests.post(url, headers=headers, timeout=timeout, data=body, json=json, verify=False)
        except requests.exceptions.RequestException as err:
            log('error retrieving response from POST {}: {}'.format(url, err.message), xbmc.LOGERROR)

        return None

    @staticmethod
    def _delete(url, headers={}, timeout=None):
        Request._logRequest('DELETE', url, headers)
        try:
            return requests.delete(url, headers=headers, timeout=timeout, verify=False)
        except requests.exceptions.RequestException as err:
            log('error retrieving response from DELETE {}: {}'.format(url, err.message), xbmc.LOGERROR)

        return None

    @staticmethod
    def _handleRequest(result, requestType):
        if not isinstance(result, requests.Response):
            raise ValueError('invalid result: {}'.format(result))
        if not requestType:
            raise ValueError('invalid requestType')

        if not result.ok:
            if result.status_code == 401:
                raise NotAuthenticatedError()

            log('failed to retrieve response from {} {}: HTTP {}'.format(requestType, result.url, result.status_code), xbmc.LOGERROR)
            return None

        return result

    @staticmethod
    def _handleRequestAsContent(result, requestType):
        if not isinstance(result, requests.Response):
            raise ValueError('invalid result: {}'.format(result))
        if not requestType:
            raise ValueError('invalid requestType')

        if not Request._handleRequest(result, requestType):
            return None

        return result.content

    @staticmethod
    def _handleRequestAsJson(result, requestType):
        if not isinstance(result, requests.Response):
            raise ValueError('invalid result: {}'.format(result))
        if not requestType:
            raise ValueError('invalid requestType')

        if not Request._handleRequest(result, requestType):
            return None

        if not result.content:
            return None

        try:
            resultObj = result.json()
            if resultObj:
                return resultObj

            log('invalid response from {} {}'.format(requestType, result.url), xbmc.LOGERROR)
        except ValueError as err:
            log('response from {} {} is not a JSON object: {}'.format(requestType, result.url, str(err)), xbmc.LOGERROR)

        return None

    @staticmethod
    def _logRequest(method, url, header=None, body=None):
        if not EMBY_API_DEBUG_ENABLED:
            return

        if not method:
            raise ValueError('invalid method')
        if not url:
            raise ValueError('invalid url')

        redactedBody = None
        if body and isinstance(body, dict):
            redactedBody = body.copy()
            # redact the body in case it contains a password
            for key in redactedBody:
                if key in (constants.PROPERTY_USER_AUTHENTICATION_PASSWORD):
                    redactedBody[key] = '****'

        log('{} {} ({}): {}'.format(method, url, header, redactedBody), xbmc.LOGDEBUG)
