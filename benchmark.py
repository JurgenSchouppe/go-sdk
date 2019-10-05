#!/usr/bin/env python
import subprocess
from multiprocessing.pool import ThreadPool
import multiprocessing
import pexpect
import os
import shutil
import json
import logging
import inspect
import datetime
import sys
import random
import math

# Use threading b/c this script mostly just calls the CLI to do the heavy lifting.

VERBOSE = True
LOAD_KEYS_THREAD_COUNT = multiprocessing.cpu_count()
ENDPOINTS = [
    "https://api.s0.b.hmny.io/",  # Endpoint for shard 0
    "https://api.s1.b.hmny.io/"   # Endpoint for shard 1
]

# TODO fix duplicate name override on CLI
# TODO define limits to be used by everybody
# https://github.com/harmony-one/harmony/blob/master/internal/configs/sharding/testnet.go
# https://github.com/harmony-one/harmony/blob/master/test/txgen/main.go


def log(message, error=True):
    func = inspect.currentframe().f_back.f_code
    final_msg = "(%s:%i) %s" % (
        func.co_name,
        func.co_firstlineno,
        message
    )
    if error:
        logging.warning(final_msg)
        if VERBOSE:
            print(f"[ERROR] {final_msg}")
    elif VERBOSE:
        print(final_msg)


def load_environment():
    assert os.path.isfile("../harmony/scripts/setup_bls_build_flags.sh")
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

    def __init__(self, environment, api_endpoints):
        """
        :param environment: Dictionary of environment variables to be used in the CLI
        :param api_endpoints: A list of api endpoints such that the i-th element is
                              the endpoint for the i-th shard.
        """
        assert os.path.isfile("hmy")
        self.environment = environment
        self.api_endpoints = api_endpoints
        self.addresses = {}
        self.keystore_path = None
        self.update_addresses()
        self.update_keystore_path()

    def update_keystore_path(self):
        try:
            response = self.single_call("hmy keys location").strip()
        except subprocess.CalledProcessError as err:
            log(f"[Critical] Could not get keystore path.\n"
                f"\tGot exit code {err.returncode}. Msg: {err.output}")
            sys.exit(-1)
        if not os.path.exists(response):
            log(f"[Critical] '{response}' is not a valid path")
            sys.exit(-1)
        self.keystore_path = response

    def update_addresses(self):
        try:
            response = self.single_call("hmy keys list")
        except subprocess.CalledProcessError as err:
            log(f"[Critical] Could not list addresses.\n"
                f"\tGot exit code {err.returncode}. Msg: {err.output}")
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
        except (shutil.Error, FileNotFoundError) as e:
            log(f"[KEY DELETE] Failed to delete dir: {key_file_path}\n"
                f"\tException: {e}")
            return
        del self.addresses[name]

    def get_balance(self, name, endpoint=0):
        """
        :param name: Alias of cli's keystore
        :param endpoint: The index of the endpoint in api_endpoints ~ which shard's endpoint
        :return: A dictionary containing the total balance and shard balances
        """
        assert endpoint < len(self.api_endpoints)
        if name not in self.addresses:
            self.update_addresses()
        if name not in self.addresses:
            return None
        try:
            response = self.single_call(f"hmy balance {self.addresses[name]} --node={self.api_endpoints[endpoint]}")
            response = response.replace("\n", "")
        except subprocess.CalledProcessError as err:
            log(f"[Critical] Could not get balance for '{name}'.\n"
                f"\tGot exit code {err.returncode}. Msg: {err.output}")
            return None
        return eval(response)  # Assumes that the return of CLI is list of dictionaries in plain text.

    def single_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :returns: Decoded string of response from hmy CLI call
        :raises: subprocess.CalledProcessError if something went wrong
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "/hmy", "hmy"}:
            command_toks = command_toks[1:]
        return subprocess.check_output(["hmy"] + command_toks, env=self.environment).decode()

    def expect_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :return: A pexpect child program
        :raises: pexpect.ExceptionPexpect if something went wrong
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "/hmy", "hmy"}:
            command_toks = command_toks[1:]
        return pexpect.spawn('./hmy', command_toks, env=self.environment)


def load_validator_keys(cli, src_keys_dir, quick_copy=False, get_funds=True):
    assert isinstance(cli, HmyCLI)
    assert os.path.isdir(src_keys_dir)
    keys_paths = os.listdir(src_keys_dir)
    funds = {}

    def load_keys(start, end):
        abs_keys_path = os.path.abspath(src_keys_dir)
        for i, file in enumerate(keys_paths[start: end]):
            if not file.endswith(".key"):
                continue
            file_path = f"{abs_keys_path}/{file}"
            account_name = f"testnetVal_{i+start}"
            if not cli.get_address(account_name):
                log(f"Adding key: ({i+start}) {file}", error=False)
                if quick_copy:
                    keystore_acc_dir = f"{cli.keystore_path}/{account_name}"
                    if not os.path.isdir(keystore_acc_dir):
                        os.mkdir(keystore_acc_dir)
                    shutil.copy(file_path, f"{keystore_acc_dir}/{file}")
                else:
                    response = cli.single_call(f"keys import-ks {file_path} {account_name}").strip()
                    if f"Imported keystore given account alias of `{account_name}`" != response:
                        log(f"Could not import validator key: {file}\n"
                            f"\tName: {account_name}")
                        continue
            if get_funds:
                log(f"Fetching balance: ({i+start}) {file}", error=False)
                funds[account_name] = cli.get_balance(account_name)

    key_count = len(keys_paths)
    pool = ThreadPool(processes=LOAD_KEYS_THREAD_COUNT)
    steps = math.ceil(key_count / LOAD_KEYS_THREAD_COUNT)
    threads = []
    for i in range(LOAD_KEYS_THREAD_COUNT):
        start_index = i * steps
        end_index = (i + 1) * steps
        threads.append(
            pool.apply_async(load_keys, (start_index, end_index)))
    for thread in threads:
        thread.get()  # Wait until each thread is done.

    return funds if get_funds else None


def fund_source_accounts(cli):
    assert isinstance(cli, HmyCLI)


if __name__ == "__main__":
    logging.basicConfig(filename="benchmark.log", filemode='a', format="%(message)s")
    logging.warning(f"[{datetime.datetime.now()}] {'=' * 10}")
    CLI = HmyCLI(environment=load_environment(), api_endpoints=ENDPOINTS)

    funds_report = load_validator_keys(CLI, "testnet_validator_keys", get_funds=True, quick_copy=True)
    print(funds_report)
    # TODO: first 'dry' run.
