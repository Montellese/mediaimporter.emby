#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2017-2019 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

import os

from six import PY3
from six.moves.urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import xbmc  # pylint: disable=import-error
import xbmcaddon  # pylint: disable=import-error
import xbmcvfs  # pylint: disable=import-error

__addon__ = xbmcaddon.Addon()
__addonid__ = __addon__.getAddonInfo('id')


def log(message, level=xbmc.LOGINFO):
    if not PY3:
        try:
            message = message.encode('utf-8')
        except UnicodeDecodeError:
            message = message.decode('utf-8').encode('utf-8', 'ignore')
    xbmc.log('[{}] {}'.format(__addonid__, message), level)


# fixes unicode problems
def string2Unicode(text, encoding='utf-8'):
    try:
        if PY3:
            text = str(text)
        else:
            text = unicode(text, encoding)  # noqa: F821
    except:  # noqa: E722  # nosec
        pass

    return text


def normalizeString(text):
    try:
        text = unicodedata.normalize('NFKD', string2Unicode(text)).encode('ascii', 'ignore')  # noqa: F821
    except:  # noqa: E722  # nosec
        pass

    return text


def localise(identifier):
    return normalizeString(__addon__.getLocalizedString(identifier))


def mediaProvider2str(mediaProvider):
    if not mediaProvider:
        return 'unknown media provider'

    return '"{}" ({})'.format(mediaProvider.getFriendlyName(), mediaProvider.getIdentifier())


def mediaImport2str(mediaImport):
    if not mediaImport:
        return 'unknown media import'

    return '{} {}'.format(mediaProvider2str(mediaImport.getProvider()), mediaImport.getMediaTypes())


# https://www.oreilly.com/library/view/python-cookbook/0596001673/ch04s16.html
def splitall(path):
    allparts = []
    while 1:
        parts = os.path.split(path)
        if parts[0] == path:  # sentinel for absolute paths
            allparts.insert(0, parts[0])
            break
        if parts[1] == path:  # sentinel for relative paths
            allparts.insert(0, parts[1])
            break

        path = parts[0]
        allparts.insert(0, parts[1])

    return allparts

def getIcon():
    iconPath = xbmcvfs.translatePath(__addon__.getAddonInfo('icon'))
    try:
        iconPath = iconPath.decode('utf-8')
    except AttributeError:
        pass

    return iconPath


class Url:
    @staticmethod
    def append(url, *args):
        if not url:
            return ''

        # remove a potentially trailing slash
        if url.endswith('/'):
            url = url[:-1]

        for arg in args:
            if not arg.startswith('/'):
                url += '/'

            url += arg

        return url

    @staticmethod
    def addOptions(url, options):
        if not url:
            return ''

        urlParts = list(urlparse(url))
        urlQuery = dict(parse_qsl(urlParts[4]))
        urlQuery.update(options)
        urlParts[4] = urlencode(urlQuery)
        return urlunparse(urlParts)

    @staticmethod
    def addTrailingSlash(url):
        if not url:
            raise ValueError('invalid url')

        return os.path.join(url, '')


try:
    from datetime import timezone
    utc = timezone.utc
except ImportError:
    from datetime import timedelta, tzinfo

    class UTC(tzinfo):
        """UTC"""

        ZERO = timedelta(0)

        def utcoffset(self, dt):
            return UTC.ZERO

        def tzname(self, dt):
            return "UTC"

        def dst(self, dt):
            return UTC.ZERO

    utc = UTC()
