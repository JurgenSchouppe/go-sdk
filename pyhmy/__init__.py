from pyhmy.cli import *

# Find the CLI binary for the default binary of the CLI object
for root, dirs, files in os.walk(os.path.curdir):
    if "hmy" in files:
        HmyCLI.hmy_binary_path = os.path.join(root, "hmy").replace("./", "")
        break