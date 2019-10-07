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
    go_path = subprocess.check_output(["go", "env", "GOPATH"]).decode().strip()
    setup_script_path = f"{go_path}/src/github.com/harmony-one/harmony/scripts/setup_bls_build_flags.sh"
    assert os.path.isfile(setup_script_path)
    response = subprocess.check_output(f"source {setup_script_path} -v", shell=True)
    environment = json.loads(response)
    environment["HOME"] = os.environ.get("HOME")
    return environment


class HmyCLI:
    hmy_binary_path = "hmy"  # This attr should be set by the __init__.py of this module.

    def __init__(self, environment, hmy_binary_path=None):
        """
        :param environment: Dictionary of environment variables to be used in the CLI
        :param hmy_binary_path: An optional path to the harmony binary; defaults to
                                class attribute.
        """
        if hmy_binary_path:
            assert os.path.isfile(hmy_binary_path)
            self.hmy_binary_path = hmy_binary_path.replace("./", "")
        self.environment = environment
        self.version = ""
        self.keystore_path = ""
        self._addresses = {}
        self._set_version()
        self._set_keystore_path()
        self._sync_addresses()

    def __repr__(self):
        return self.version

    def _set_version(self):
        """
        Internal method to set this instance's version according to the binary's version.
        """
        proc = subprocess.Popen([self.hmy_binary_path, "version"], env=self.environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        if not err:
            raise RuntimeError(f"Could not get version.\n"
                               f"\tGot exit code {proc.returncode}. Expected non-empty error message.")
        self.version = err.decode()

    def _set_keystore_path(self):
        """
        Internal method to set this instance's keystore path with the binary's keystore path.
        """
        try:
            response = self.single_call("hmy keys location").strip()
        except subprocess.CalledProcessError as err:
            raise RuntimeError(f"Could not get keystore path.\n"
                               f"\tGot exit code {err.returncode}. Msg: {err.output}")
        if not os.path.exists(response):
            raise ValueError(f"'{response}' is not a valid path")
        self.keystore_path = response

    def _sync_addresses(self):
        """
        Internal method to sync this instance's address with the binary's keystore addresses.
        """
        try:
            response = self.single_call("hmy keys list")
        except subprocess.CalledProcessError as err:
            raise RuntimeError(f"Could not list _addresses.\n"
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
                self._addresses[name.strip()] = address

    def get_address(self, name):
        """
        :param name: The alias of a key used in the CLI's keystore.
        :return: The associated 'one1...' address.
        """
        if name in self._addresses:
            return self._addresses[name]
        else:
            self._sync_addresses()
            return self._addresses.get(name, None)

    def remove_address(self, name):
        """
        :param name: The alias of a key used in the CLI's keystore.
        """
        key_file_path = f"{self.keystore_path}/{name}"
        try:
            shutil.rmtree(key_file_path)
        except (shutil.Error, FileNotFoundError) as e:
            raise RuntimeError(f"Failed to delete dir: {key_file_path}\n"
                               f"\tException: {e}")
        del self._addresses[name]

    def single_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :returns: Decoded string of response from hmy CLI call
        :raises: RuntimeError if CLI returns an error
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "/hmy", "hmy"}:
            command_toks = command_toks[1:]
        command_toks = [self.hmy_binary_path] + command_toks
        proc = subprocess.Popen(command_toks, env=self.environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = proc.communicate()
        if err:
            raise RuntimeError(f"CLI returned error by executing {' '.join(command_toks)}\n"
                               f"\tGot exit code {proc.returncode}. Msg: {err.decode()}")
        return out.decode()

    def expect_call(self, command):
        """
        :param command: String fo command to execute on CLI
        :return: A pexpect child program
        :raises: pexpect.ExceptionPexpect if bad command
        """
        command_toks = command.split(" ")
        if command_toks[0] in {"./hmy", "/hmy", "hmy"}:
            command_toks = command_toks[1:]
        return pexpect.spawn(f"./{self.hmy_binary_path}", command_toks, env=self.environment)
