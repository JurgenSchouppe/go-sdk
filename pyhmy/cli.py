import subprocess
import pexpect
import json
import os
import shutil


def get_environment():
    """
    Fetches the environment variables from the 'setup_bls_build_flags.sh' script
    in the harmony main repo. Also fetches the 'HOME' environment variable for HmyCLI.
    """
    try:
        go_path = subprocess.check_output(["go", "env", "GOPATH"]).decode().strip()
        bls_setup_path = f"{go_path}/src/github.com/harmony-one/harmony/scripts/setup_bls_build_flags.sh"
        assert os.path.isfile(bls_setup_path)
        env_raw = subprocess.check_output(f"source {bls_setup_path} -v", shell=True)
        environment = json.loads(env_raw)
        environment["HOME"] = os.environ.get("HOME")
    except (AssertionError, json.decoder.JSONDecodeError, subprocess.CalledProcessError) as _:
        raise RuntimeError(f"Could not parse environment variables from setup_bls_build_flags.sh")
    return environment


class HmyCLI:

    hmy_binary_path = "hmy"  # This attr should be set by the __init__.py of this module.

    def __init__(self, environment, api_endpoints, hmy_binary_path=None):
        """
        :param environment: Dictionary of environment variables to be used in the CLI
        :param api_endpoints: A list of api endpoints such that the i-th element is
                              the endpoint for the i-th shard.
        :param hmy_binary_path:
        """
        # TODO: get version and store it as attribute.

        if hmy_binary_path:
            self.hmy_binary_path = hmy_binary_path.replace("./", "")
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
            raise RuntimeError(f"Could not get keystore path.\n"
                               f"\tGot exit code {err.returncode}. Msg: {err.output}")
        if not os.path.exists(response):
            raise ValueError(f"'{response}' is not a valid path")
        self.keystore_path = response

    def update_addresses(self):
        try:
            response = self.single_call("hmy keys list")
        except subprocess.CalledProcessError as err:
            raise RuntimeError(f"Could not list addresses.\n"
                               f"\tGot exit code {err.returncode}. Msg: {err.output}")
        lines = response.split("\n")
        if "NAME" not in lines[0] or "ADDRESS" not in lines[0]:
            raise ValueError(f"Name or Address not found on first line if key list")
        for line in lines[1:]:
            if line:
                columns = line.split("\t")
                if len(columns) != 2:
                    raise ValueError("Unexpected format of keys list")
                name, address = columns
                self.addresses[name.strip()] = address

    def get_address(self, name):
        if name in self.addresses:
            return self.addresses[name]
        else:
            self.update_addresses()
            return self.addresses.get(name, None)

    def remove_address(self, name):
        key_file_path = f"{self.keystore_path}/{name}"
        try:
            shutil.rmtree(key_file_path)
        except (shutil.Error, FileNotFoundError) as e:
            raise RuntimeError(f"Failed to delete dir: {key_file_path}\n"
                               f"\tException: {e}")
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
            raise RuntimeError(f"[Critical] Could not get balance for '{name}'.\n"
                               f"\tGot exit code {err.returncode}. Msg: {err.output}")
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
        return subprocess.check_output([self.hmy_binary_path] + command_toks, env=self.environment).decode()

    def expect_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :return: A pexpect child program
        :raises: pexpect.ExceptionPexpect if something went wrong
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "/hmy", "hmy"}:
            command_toks = command_toks[1:]
        return pexpect.spawn(f"./{self.hmy_binary_path}", command_toks, env=self.environment)
