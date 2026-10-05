import json

import requests


class WgGesuchtClient:
    """Small unofficial client for the WG-Gesucht mobile API."""

    API_URL = 'https://www.wg-gesucht.de/api/{}'
    APP_VERSION = '1.28.0'
    APP_PACKAGE = 'com.wggesucht.android'
    CLIENT_ID = 'wg_mobile_app'
    USER_AGENT = (
        'Mozilla/5.0 (Linux; Android 6.0; Google Build/MRA58K; wv) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 '
        'Chrome/74.0.3729.186 Mobile Safari/537.36'
    )

    def __init__(self):
        self.userId = None
        self.accessToken = None
        self.refreshToken = None
        self.phpSession = None
        self.devRefNo = None

    def request(self, method: str, endpoint: str, params: object = None, payload: object = None, attempt: int = 0):
        cookies = [
            f'PHPSESSID={self.phpSession}' if self.phpSession else None,
            f'X-Client-Id={self.CLIENT_ID}',
            f'X-Refresh-Token={self.refreshToken}' if self.refreshToken else None,
            f'X-Access-Token={self.accessToken}' if self.accessToken else None,
            f'X-Dev-Ref-No={self.devRefNo}' if self.devRefNo else None,
        ]
        headers = {
            'X-App-Version': self.APP_VERSION,
            'User-Agent': self.USER_AGENT,
            'Content-Type': 'application/json',
            'Accept-Encoding': 'gzip, deflate',
            'Accept': 'application/json',
            'X-Client-Id': self.CLIENT_ID,
            'X-Authorization': f'Bearer {self.accessToken}' if self.accessToken else None,
            'X-User-Id': self.userId if self.userId else None,
            'X-Dev-Ref-No': self.devRefNo if self.devRefNo else None,
            'Cookie': '; '.join(value for value in cookies if value),
            'X-Requested-With': self.APP_PACKAGE,
            'Origin': 'file://' if not self.accessToken else None,
        }
        response = requests.request(
            method=method,
            url=self.API_URL.format(endpoint),
            headers={key: value for key, value in headers.items() if value is not None},
            params=params,
            data=payload,
            timeout=30,
        )
        if 200 <= response.status_code < 300:
            return response
        if response.status_code == 401 and attempt < 1 and self.refreshToken:
            if self.refreshAccessToken():
                return self.request(method, endpoint, params, payload, attempt + 1)
        return None

    def importAccount(self, config: object):
        self.userId = config['userId']
        self.accessToken = config['accessToken']
        self.refreshToken = config['refreshToken']
        self.phpSession = config['phpSession']
        self.devRefNo = config['devRefNo']

    def exportAccount(self):
        return {
            'userId': self.userId,
            'accessToken': self.accessToken,
            'refreshToken': self.refreshToken,
            'phpSession': self.phpSession,
            'devRefNo': self.devRefNo,
        }

    def login(self, username: str, password: str):
        payload = {
            'login_email_username': username,
            'login_password': password,
            'client_id': self.CLIENT_ID,
            'display_language': 'de',
        }
        response = self.request('POST', 'sessions', payload=json.dumps(payload))
        if not response:
            return False
        detail = response.json()['detail']
        self.accessToken = detail['access_token']
        self.refreshToken = detail['refresh_token']
        self.userId = detail['user_id']
        self.devRefNo = detail['dev_ref_no']
        self.phpSession = response.cookies.get('PHPSESSID')
        return True

    def refreshAccessToken(self):
        payload = {
            'grant_type': 'refresh_token',
            'access_token': self.accessToken,
            'refresh_token': self.refreshToken,
            'client_id': self.CLIENT_ID,
            'dev_ref_no': self.devRefNo,
            'display_language': 'de',
        }
        response = self.request(
            'POST',
            f'sessions/users/{self.userId}',
            payload=json.dumps(payload),
            attempt=1,
        )
        if not response:
            return False
        detail = response.json()['detail']
        self.accessToken = detail['access_token']
        self.refreshToken = detail['refresh_token']
        self.devRefNo = detail['dev_ref_no']
        return True

    def myProfile(self):
        response = self.request('GET', f'public/users/{self.userId}')
        return response.json() if response else False

    def findCity(self, query: str):
        response = self.request('GET', f'location/cities/names/{query}')
        return response.json()['_embedded']['cities'] if response else False

    def offers(self, cityId: str, categories: str, maxRent: str, minSize: str, page: str = '1'):
        params = {
            'ad_type': '0',
            'categories': categories,
            'city_id': cityId,
            'noDeact': '1',
            'img': '1',
            'limit': '20',
            'rMax': maxRent,
            'sMin': minSize,
            'rent_types': categories,
            'page': page,
        }
        response = self.request('GET', 'asset/offers/', params=params)
        return response.json()['_embedded']['offers'] if response else False

    def offerDetail(self, offerId: str):
        response = self.request('GET', f'public/offers/{offerId}')
        return response.json() if response else False

    def contactOffer(self, offerId: str, message: str):
        payload = {
            'user_id': self.userId,
            'ad_type': 0,
            'ad_id': int(offerId),
            'messages': [{'content': message, 'message_type': 'text'}],
        }
        response = self.request('POST', 'conversations', payload=json.dumps(payload))
        return response.json().get('messages', []) if response else False

    def conversations(self, page: str = '1'):
        params = {'page': page, 'limit': '25', 'language': 'de', 'filter_type': '0'}
        response = self.request('GET', f'conversations/user/{self.userId}', params=params)
        return response.json().get('_embedded', {}).get('conversations', []) if response else False

    def conversationDetail(self, conversationId: str):
        response = self.request(
            'GET',
            f'conversations/{conversationId}/user/{self.userId}',
            params={'language': 'de'},
        )
        return response.json() if response else False
