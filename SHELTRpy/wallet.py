import asyncio  # important!!
import json
from SHELTRpy.request import request  # import our request function.
import time
from js import storeData, getData, getAddrFromXpub

from SHELTRpy.ghostCrypto import password_decrypt, password_encrypt, getToken

from pyodide.ffi import to_js
import js

from types import SimpleNamespace

from binascii import unhexlify

from pyscript import Element


class ImportWalletFromDump:
    def __init__(self, core_dump) -> None:
        self.dump = core_dump
        self.derived_xpub = core_dump['accounts'][0]['chains'][0]['chain']
        self.derived_xpriv = core_dump['accounts'][0]['chains'][0]['evkey']
        self.xpub = "IMPORTFROMDUMP"
        self.xpriv = "IMPORTFROMDUMP"
        self.words = "IMPORTFROMDUMP"
        self.derived_xpub_change = core_dump['accounts'][0]['chains'][1]['chain']
        self.derived_xpriv_change = core_dump['accounts'][0]['chains'][1]['evkey']

class ImportWallet:
    def __init__(self, wallet: dict):
        self.wallet = wallet
        self.wallet["receiving_addresses"] = self.getAddresses(0, 1)
        self.wallet["lookahead_addresses"] = self.getAddresses(1, wallet['gap_limit'] + 1)
        self.wallet["receiving_addresses_256"] = self.getAddresses(0, 1, is256=True)
        self.wallet["lookahead_addresses_256"] = self.getAddresses(
            1, wallet['gap_limit'] + 1, is256=True
        )
        self.wallet["change_addresses"] = self.getAddresses(
            0, 1, is256=False, isChange=True
        )
        self.wallet["change_lookahead_addresses"] = self.getAddresses(
            1, wallet['gap_limit'] + 1, is256=False, isChange=True
        )

    def getAddresses(self, startIdx, endIdx, is256=False, isChange=False):
        addresses = []
        for index in range(startIdx, endIdx):
            if not isChange:
                addr = getAddrFromXpub(str(self.wallet["xpub"]), index, is256)
            else:
                addr = getAddrFromXpub(str(self.wallet["xpub_change"]), index, is256)
            addresses.append(str(addr))
            if not is256 and not isChange:
                self.wallet["master_address_list"].append(str(addr))
            elif isChange:
                self.wallet["change_master_address_list"].append(str(addr))
        return addresses


class Wallet:
    def __init__(self, TOKEN, api):
        self.token = TOKEN[2:-1]
        self.dec_wallet = None
        self.wallet = None
        self.api = api

    async def initialize(self, password):
        self.dec_wallet = await self.getDecWallet()
        self.wallet = SimpleNamespace(**self.dec_wallet)
        self.checkIntegrity()

        await self.rotate_token(password)

        if "gap_limit" not in dir(self.wallet):
            self.wallet.gap_limit = 20
            await self.flushWallet()

    async def rotate_token(self, password):
        new_token = getToken()
        await storeData(
            "TOKEN",
            str(
                await password_encrypt(new_token.encode(), password),
                "utf-8",
            ),
        )

        self.token = new_token
        await self.flushWallet()

    async def getDecWallet(self):
        wallet = json.loads(
            await password_decrypt(
                str(await getData("wallet").then(lambda x: x)), self.token
            )
        )
        return wallet

    async def flushWallet(self):
        await storeData(
            "wallet",
            str(
                await password_encrypt(
                    str(json.dumps(vars(self.wallet))).encode(), self.token
                ),
                "utf-8",
            ),
        )

    def checkIntegrity(self):
        for index, addr in enumerate(self.wallet.receiving_addresses):
            assert str(getAddrFromXpub(self.wallet.xpub, index)) == addr

    async def processUTXO(self):
        currentAddrs = (
            self.wallet.receiving_addresses
            + self.wallet.receiving_addresses_256
            + self.wallet.change_addresses
        )
        addrStr = ""

        for addr in currentAddrs:
            addrStr += f",{addr}"
        addrStr = addrStr[1:]
        utxo = await self.api.getMultiAddrUtxoPost(addrStr)

        self.wallet.utxo = utxo

        balance = 0
        cs_balance = 0
        unconf_balance = 0

        for idx in self.wallet.utxo:
            balance += idx["satoshis"]

            if self.isCsOut(idx["script"]):
                cs_balance += idx["satoshis"]

            if idx["confirmations"] < 1:
                unconf_balance += idx["satoshis"]

        self.wallet.unconfirmedBalance = unconf_balance
        self.wallet.coldstakingBalance = cs_balance
        self.wallet.totalBalance = balance

        await self.flushWallet()

    def convertFromSat(self, value):
        sat_readable = value / 10**8
        return sat_readable

    def convertToSat(self, value):
        sat_readable = value * 10**8
        return sat_readable

    def isCsOut(self, scriptPubKey):
        if not (len(scriptPubKey) % 2) == 0:
            return False

        if not self.checkHex(scriptPubKey):
            return False

        script_hex = unhexlify(scriptPubKey)

        if (
            len(script_hex) == 66
            and script_hex[0] == 0xB8
            and script_hex[1] == 0x63
            and script_hex[2] == 0x76
            and script_hex[3] == 0xA9
            and script_hex[4] == 0x14
            and script_hex[25] == 0x88
            and script_hex[26] == 0xAC
            and script_hex[27] == 0x67
            and script_hex[28] == 0x76
            and script_hex[29] == 0xA8
            and script_hex[30] == 0x20
            and script_hex[63] == 0x88
            and script_hex[64] == 0xAC
            and script_hex[65] == 0x68
        ):
            return True
        else:
            return False

    def checkHex(self, s):
        for ch in s.lower():
            if (ch < "0" or ch > "9") and (ch < "a" or ch > "f"):
                return False

        return True

    async def isMine(self, addr):
        if (
            addr in self.wallet.master_address_list
            or addr in self.wallet.receiving_addresses_256
            or addr in self.wallet.lookahead_addresses_256
            or addr in self.wallet.change_master_address_list
        ):
            return True
        else:
            return False

    async def task_runner(self):
        pass
        # while True:
        #    pass
        # await asyncio.sleep(60)
