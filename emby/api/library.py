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
        def __init__(self, identifier, name, mediaType):
            self.id = identifier
            self.name = name
            self.mediaType = mediaType

        @staticmethod
        def fromObject(viewObj):
            if not viewObj:
                raise ValueError('invalid viewObj')

            view = Library.View(
                viewObj[constants.PROPERTY_VIEW_ID],
                viewObj[constants.PROPERTY_VIEW_NAME],
                viewObj.get(constants.PROPERTY_VIEW_COLLECTION_TYPE, 'mixed'))

            if not view.id or not view.name or not view.mediaType:
                return None

            return view

    @staticmethod
    def GetViews(embyServer, mediaTypes, includeMixed=False):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not mediaTypes:
            raise ValueError('invalid mediaTypes')

        viewsUrl = embyServer.BuildUserUrl(constants.URL_VIEWS)
        resultObj = embyServer.ApiGet(viewsUrl)
        if not resultObj or constants.PROPERTY_ITEM_ITEMS not in resultObj:
            return []

        viewsObj = resultObj[constants.PROPERTY_ITEM_ITEMS]
        libraryViews = []
        for viewObj in viewsObj:
            if constants.PROPERTY_VIEW_ID not in viewObj or \
               constants.PROPERTY_VIEW_NAME not in viewObj:
                continue

            # mixed libraries don't have a CollectionType attribute
            mixedView = constants.PROPERTY_VIEW_COLLECTION_TYPE not in viewObj
            if mixedView and not includeMixed:
                continue

            if not mixedView:
                mediaType = viewObj[constants.PROPERTY_VIEW_COLLECTION_TYPE]
                if not mediaType:
                    continue

                matchingMediaTypes = [type for type in mediaTypes if mediaType in (type, type + 's')]
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

    @staticmethod
    def RefreshItemMetadata(embyServer, itemId):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        itemRefreshUrl = embyServer.BuildItemRefreshUrl(itemId)
        return embyServer.ApiPost(itemRefreshUrl, json={
            constants.URL_QUERY_ITEMS_RECURSIVE: True,
            constants.URL_QUERY_ITEMS_REFRESH_METADATA_MODE: constants.URL_QUERY_ITEMS_REFRESH_MODE_FULL,
            constants.URL_QUERY_ITEMS_REFRESH_IMAGE_MODE: constants.URL_QUERY_ITEMS_REFRESH_MODE_FULL,
            constants.URL_QUERY_ITEMS_REFRESH_REPLACE_ALL_METADATA: True,
            constants.URL_QUERY_ITEMS_REFRESH_REPLACE_ALL_IMAGES: False
        })

    @staticmethod
    def GetLocalTrailers(embyServer, itemId):
        if not embyServer:
            raise ValueError('invalid embyServer')
        if not itemId:
            raise ValueError('invalid itemId')

        localTrailersUrl = embyServer.BuildLocalTrailersUrl(itemId)
        return embyServer.ApiGet(localTrailersUrl)
