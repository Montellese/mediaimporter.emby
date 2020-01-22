#!/usr/bin/python
# -*- coding: utf-8 -*-
#  Copyright (C) 2020 Sascha Montellese <montellese@kodi.tv>
#
#  SPDX-License-Identifier: GPL-2.0-or-later
#  See LICENSES/README.md for more information.
#

from emby import constants

class Library:
    class View:
        def __init__(self, id, name, mediaType):
            self.id = id
            self.name = name
            self.mediaType = mediaType

        @staticmethod
        def fromObject(viewObj):
            if not viewObj:
                raise ValueError('invalid viewObj')

            view = Library.View( \
                viewObj[constants.PROPERTY_VIEW_ID], \
                viewObj[constants.PROPERTY_VIEW_NAME], \
                viewObj[constants.PROPERTY_VIEW_COLLECTION_TYPE])

            if not view.id or not view.name or not view.mediaType:
                return None

            return view

    @staticmethod
    def GetViews(embyServer, mediaTypes):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not mediaTypes:
            raise ValueError('invalid mediaTypes')

        viewsUrl = embyServer.BuildUserUrl(constants.URL_VIEWS)
        resultObj = embyServer.ApiGet(viewsUrl)
        if not resultObj or not constants.PROPERTY_ITEM_ITEMS in resultObj:
            return []

        viewsObj = resultObj[constants.PROPERTY_ITEM_ITEMS]
        libraryViews = []
        for viewObj in viewsObj:
            if not constants.PROPERTY_VIEW_ID in viewObj or \
                not constants.PROPERTY_VIEW_NAME in viewObj or \
                not constants.PROPERTY_VIEW_COLLECTION_TYPE in viewObj:
                continue

            mediaType = viewObj[constants.PROPERTY_VIEW_COLLECTION_TYPE]
            if not mediaType:
                continue

            matchingMediaTypes = [ type for type in mediaTypes if mediaType == type or mediaType == type + 's' ]
            if not matchingMediaTypes:
                continue

            libraryView = Library.View.fromObject(viewObj)
            if not libraryView:
                continue

            libraryViews.append(libraryView)

        return libraryViews

    @staticmethod
    def GetItem(embyServer, itemId):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        itemUrl = embyServer.BuildUserItemUrl(itemId)
        return embyServer.ApiGet(itemUrl)
