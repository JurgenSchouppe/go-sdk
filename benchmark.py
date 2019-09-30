#!/usr/bin/env python
import subprocess
from multiprocessing.pool import ThreadPool
import pexpect
import os
import shutil
import json
import logging
import inspect
import datetime
import sys
import random


def log(message, error=True):
    func = inspect.currentframe().f_back.f_code
    final_msg = "(%s:%i) %s" % (
        func.co_name,
        func.co_firstlineno,
        message
    )
    if error:
        logging.warning(final_msg)
        print(f"[ERROR] {final_msg}")
    else:
        print(final_msg)


def load_environment():
    try:
        # Requires the updated 'setup_bls_build_flags.sh'
        env_raw = subprocess.check_output("source ../harmony/scripts/setup_bls_build_flags.sh -v", shell=True)
        environment = json.loads(env_raw)
        environment["HOME"] = os.environ.get("HOME")
    except json.decoder.JSONDecodeError as _:
        log(f"[Critical] Could not parse environment variables from setup_bls_build_flags.sh")
        sys.exit(-1)
    return environment


class HmyCLI:

    def __init__(self, environment):
        assert os.path.isfile("hmy")
        self.environment = environment
        self.addresses = {}
        self.keystore_path = None
        self.update_addresses()
        self.update_keystore_path()

    def update_keystore_path(self):
        try:
            response = subprocess.check_output(["hmy", "keys", "location"], env=self.environment).decode().strip()
        except subprocess.CalledProcessError as err:
            log(f"[Critical] Could not get keystore path.\n"
                f"Got exit code {err.returncode}. Msg: {err.output}")
            sys.exit(-1)
        if not os.path.exists(response):
            log(f"[Critical] '{response}' is not a valid path")
            sys.exit(-1)
        self.keystore_path = response

    def update_addresses(self):
        try:
            response = subprocess.check_output(["hmy", "keys", "list"], env=self.environment).decode()
        except subprocess.CalledProcessError as err:
            log(f"[Critical] Could not list addresses.\n"
                f"Got exit code {err.returncode}. Msg: {err.output}")
            sys.exit(-1)

        lines = response.split("\n")
        if "NAME" not in lines[0] or "ADDRESS" not in lines[0]:
            log(f"[Critical] Name or Address not found on first line if key list.")
            sys.exit(-1)

        for line in lines[1:]:
            if not line:
                continue
            try:
                name, address = line.split("\t")
            except ValueError:
                log(f"[Critical] Unexpected key list format.")
                sys.exit(-1)
            self.addresses[name.strip()] = address

    def get_address(self, name):
        if name in self.addresses:
            return self.addresses[name]
        else:
            self.update_addresses()
            return self.addresses.get(name, None)

    def remove_address(self, name):
        log(f"[KEY DELETE] Removing {name} from keystore at {self.keystore_path}", error=False)
        key_file_path = f"{self.keystore_path}/{name}"

        try:
            shutil.rmtree(key_file_path)
        except shutil.Error as e:
            log(f"[KEY DELETE] Failed to delete dir: {key_file_path}\n"
                f"Exception: {e}")
            return

        del self.addresses[name]

    def single_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :returns: Decoded string of response from hmy CLI call
        :raises: subprocess.CalledProcessError if something went wrong
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "hmy"}:
            command_toks = command_toks[1:]
        return subprocess.check_output(["hmy"] + command_toks, env=self.environment).decode()

    def expect_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :return: A pexpect child program
        :raises: pexpect.ExceptionPexpect if something went wrong
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "hmy"}:
            command_toks = command_toks[1:]
        return pexpect.spawn('./hmy', command_toks, env=self.environment)


def test_mnemonics_from_sdk(cli):
    assert isinstance(cli, HmyCLI)
    addresses_added = set()
    log("Testing...", error=False)

    with open('testHmyConfigs/sdkMnemonics.json') as f:
        sdk_mnemonics = json.load(f)
        if not sdk_mnemonics:
            log("Could not load reference data.")
            return False

    passed = True
    for test in sdk_mnemonics["data"]:
        index = test["index"]
        if index != 0:  # CLI currently uses a hardcoded index of 0.
            continue

        mnemonic = test["phrase"]
        correct_address = test["addr"]
        address_name = f'testHmyAcc_{random.randint(0,1e9)}'
        while address_name in cli.addresses:
            address_name = f'testHmyAcc_{random.randint(0,1e9)}'

        try:
            hmy = cli.expect_call(f"./hmy keys add {address_name} --recover --passphrase")
            hmy.expect("Enter passphrase for account\r\n".encode())
            hmy.sendline("")
            hmy.expect("Repeat the passphrase:\r\n".encode())
            hmy.sendline("")
            hmy.expect("Enter mnemonic to recover keys from\r\n".encode())
            hmy.sendline(mnemonic)
            hmy.expect(pexpect.EOF)
        except pexpect.ExceptionPexpect as e:
            log(f"Exception occurred when adding a key with mnemonic."
                f"\nException: {e}")
            passed = False

        hmy_address = cli.get_address(address_name)
        if hmy_address != correct_address or hmy_address is None:
            log(f"address does not match sdk's address. \n"
                f"\tMnemonic: {mnemonic}\n"
                f"\tCorrect address: {correct_address}\n"
                f"\tCLI address: {hmy_address}")
            passed = False
        else:
            addresses_added.add(address_name)

    for address in addresses_added:
        cli.remove_address(address)

    return passed


if __name__ == "__main__":
    logging.basicConfig(filename="benchmark.log", filemode='a', format="%(message)s")
    logging.warning(f"[{datetime.datetime.now()}] {'=' * 10}")
    CLI = HmyCLI(environment=load_environment())

    test_mnemonics_from_sdk(CLI)


    # tests_results = []
    # pool = ThreadPool(processes=4)
    # t1 = pool.apply_async(test_mnemonics_from_sdk,)
    # t2 = pool.apply_async(test_mnemonics_from_sdk,)
    # t3 = pool.apply_async(test_mnemonics_from_sdk,)
    # t4 = pool.apply_async(test_mnemonics_from_sdk,)
    # tests_results.append(t1.get())
    # tests_results.append(t2.get())
    # tests_results.append(t3.get())
    # tests_results.append(t4.get())



    #
    # for name in KEYS_ADDED:
    #     delete_from_keystore_by_name(name)
    #
    # if all(tests_results):
    #     print("\nPassed all tests!\n")
    # else:
    #     print("\nFailed some tests, check logs.\n")
    #     sys.exit(-1)
