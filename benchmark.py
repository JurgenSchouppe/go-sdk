#!/usr/bin/env python
from multiprocessing.pool import ThreadPool
import multiprocessing
import subprocess
import os
import shutil
import logging
import inspect
import datetime
import math
import pyhmy

# Use threading b/c this script mostly just calls the CLI to do the heavy lifting.

AMT_PER_TXN = 1e-3
NUM_SRC_ACC = 100
INITIAL_ACC_BALANCE = 10

VERBOSE = True
LOAD_KEYS_THREAD_COUNT = multiprocessing.cpu_count()
ENDPOINTS = [  # Note that order matters for this script
    "https://api.s0.b.hmny.io/",  # Endpoint for shard 0
    "https://api.s1.b.hmny.io/",  # Endpoint for shard 1
]


# TODO fix duplicate name override on CLI
# TODO define limits to be used by everybody
# https://github.com/harmony-one/harmony/blob/master/internal/configs/sharding/testnet.go
# https://github.com/harmony-one/harmony/blob/master/test/txgen/aamain.go


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
            print(f"[LOGGED] {final_msg}")
    elif VERBOSE:
        print(final_msg)


def get_balance(cli, name, shard=0):
    assert shard < len(ENDPOINTS)
    address = cli.get_address(name)
    if not address:
        return None
    try:
        response = cli.single_call(f"hmy balance {address} --node={ENDPOINTS[shard]}")
        response = response.replace("\n", "")
    except subprocess.CalledProcessError as err:
        raise RuntimeError(f"Could not get balance for '{name}'.\n"
                           f"\tGot exit code {err.returncode}. Msg: {err.output}")
    return eval(response)  # Assumes that the return of CLI is list of dictionaries in plain text.


def load_validator_keys(cli, src_keys_dir, quick_copy=False, get_funds=True):
    assert isinstance(cli, pyhmy.HmyCLI)
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
                funds[account_name] = get_balance(cli, account_name)

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
    assert isinstance(cli, pyhmy.HmyCLI)


if __name__ == "__main__":
    logging.basicConfig(filename="benchmark.log", filemode='a', format="%(message)s")
    logging.warning(f"[{datetime.datetime.now()}] {'=' * 20}")
    CLI = pyhmy.HmyCLI(environment=pyhmy.get_environment())
    log(f"[CLI Version] {CLI.version}")

    funds_report = load_validator_keys(CLI, "testnet_validator_keys", get_funds=True, quick_copy=True)
    print(funds_report)
    # TODO: first 'dry' run.
