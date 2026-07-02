"""
Модуль для работы с Crypto Pay API (@CryptoBot)
Документация: https://help.send.tg/en/articles/10279948-crypto-pay-api
"""

import aiohttp
import logging

logger = logging.getLogger(__name__)

CRYPTO_PAY_API_URL = "https://pay.crypt.bot/api"


class CryptoPay:
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Crypto-Pay-API-Token": token}

    async def _request(self, method: str, params: dict = None) -> dict:
        """Отправить запрос к Crypto Pay API."""
        url = f"{CRYPTO_PAY_API_URL}/{method}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    error = data.get("error", {})
                    logger.error(f"CryptoPay API error: {error}")
                    raise Exception(f"CryptoPay API error: {error}")
                return data.get("result")

    async def create_invoice(
        self,
        amount: float,
        currency_type: str = "fiat",
        fiat: str = "USD",
        accepted_assets: str = None,
        description: str = "",
        payload: str = "",
        expires_in: int = 3600,
    ) -> dict:
        """Создать инвойс для оплаты.
        
        Args:
            amount: Сумма
            currency_type: 'crypto' или 'fiat'
            fiat: Валюта (USD, EUR, RUB и др.)
            accepted_assets: Принимаемые крипто (USDT,BTC,TON и др.)
            description: Описание
            payload: Данные для webhook
            expires_in: Время жизни в секундах
            
        Returns:
            dict с полями: invoice_id, bot_invoice_url, mini_app_invoice_url и др.
        """
        params = {
            "amount": str(amount),
            "currency_type": currency_type,
            "description": description,
            "payload": payload,
            "expires_in": expires_in,
        }

        if currency_type == "fiat":
            params["fiat"] = fiat
        
        if accepted_assets:
            params["accepted_assets"] = accepted_assets

        url = f"{CRYPTO_PAY_API_URL}/createInvoice"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers, params=params) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    error = data.get("error", {})
                    logger.error(f"CryptoPay createInvoice error: {error}")
                    raise Exception(f"CryptoPay error: {error}")
                return data.get("result")

    async def get_invoices(self, invoice_ids: str = None, status: str = None) -> list:
        """Получить список инвойсов."""
        params = {}
        if invoice_ids:
            params["invoice_ids"] = invoice_ids
        if status:
            params["status"] = status
        return await self._request("getInvoices", params)

    async def get_me(self) -> dict:
        """Проверить подключение к API."""
        return await self._request("getMe")
