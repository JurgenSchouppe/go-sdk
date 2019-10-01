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


LOAD_KEY_THREAD_COUNT = multiprocessing.cpu_count()
# TODO fix duplicate name override
# TODO define limits to be used by everybody
# https://github.com/harmony-one/harmony/blob/master/internal/configs/sharding/testnet.go


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
                f"\tGot exit code {err.returncode}. Msg: {err.output}")
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
        if command_toks[0] in {"./hmy", "hmy"}:
            command_toks = command_toks[1:]
        return pexpect.spawn('./hmy', command_toks, env=self.environment)


def load_all_validator_keys(cli, keys_dir):
    assert isinstance(cli, HmyCLI)
    assert os.path.isdir(keys_dir)
    keys_paths = os.listdir(keys_dir)

    def load_keys(start, end):
        log(f"Loading validator keys from: {start} to: {end}", error=False)
        abs_keys_path = os.path.abspath(keys_dir)
        for i, file in enumerate(keys_paths[start: end]):
            if not file.endswith(".key"):
                continue

            log(f"Adding key: ({i+start}) {file}", error=False)

            file_path = f"{abs_keys_path}/{file}"
            account_name = f"testnetVal_{i+start}"
            if not cli.get_address(account_name):
                response = cli.single_call(f"keys import-ks {file_path} {account_name}").strip()
                if f"Imported keystore given account alias of `{account_name}`" != response:
                    log(f"Could not import validator key: {file}\n\t"
                        f"Name: {account_name}")
                    continue

    key_count = len(keys_paths)
    pool = ThreadPool(processes=LOAD_KEY_THREAD_COUNT)
    steps = math.ceil(key_count / LOAD_KEY_THREAD_COUNT)
    threads = []
    for i in range(LOAD_KEY_THREAD_COUNT):
        start_index = i * steps
        end_index = (i + 1) * steps
        threads.append(
            pool.apply_async(load, (start_index, end_index)))

    for thread in threads:
        thread.get()


def fund_source_accounts(cli):
    assert isinstance(cli, HmyCLI)


if __name__ == "__main__":
    logging.basicConfig(filename="benchmark.log", filemode='a', format="%(message)s")
    logging.warning(f"[{datetime.datetime.now()}] {'=' * 10}")
    CLI = HmyCLI(environment=load_environment())

    load_all_validator_keys(CLI, "testnet_validator_keys")
