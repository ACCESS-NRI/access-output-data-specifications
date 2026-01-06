"""
A simple script to update a Zenodo record with a new version with file artefacts
"""

import os
import argparse
import requests
import json
import logging

logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        prog="zenodo_update",
        description="Updates a given Zenodo record to a new version and updates the files attached to that record",
    )

    parser.add_argument(
        "--access-token", required=True, help="The Zenodo API access token to use"
    )
    parser.add_argument(
        "--production",  
        action="store_true",
        help="Use the real Zenodo environment instead of the sandbox for testing",
    )
    parser.add_argument(
        "--version", required=True, help="New version to use for the record"
    )
    parser.add_argument("--id", required=True, help="The id of the record to update")
    parser.add_argument(
        "--files",
        nargs="*",
        help="A list of file paths to upload to the record. Note: any files in the old version will be removed.",
    )
    parser.add_argument(
        "--filenames",
        nargs="*",
        help="A list of file names to use for the files when uploaded. Order and number must match the --files argument.",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Leave the new version of the record as a draft to be published manually",
    )
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    if args.filenames:
        assert len(args.files) == len(args.filenames), (
            "Number of files and destination filenames must match."
        )

    return args


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.debug("Log level set to DEBUG")

    logging.debug(f"Commandline arguments: {args}")

    if args.production:
        zenodo_api = "https://zenodo.org/api"
    else:
        zenodo_api = "https://sandbox.zenodo.org/api"

    logging.debug(f"Zenodo API target set to {zenodo_api}")

    # Setup the header
    headers = {"Authorization": f"Bearer {args.access_token}"}

    try:
        # Get the metadata for this record
        logging.debug(f"Getting data for deposition {args.id}")
        response = requests.get(
            f"{zenodo_api}/deposit/depositions/{args.id}", headers=headers
        )
        response.raise_for_status()

        # Create a new deposition
        logging.debug("Creating new deposition")
        response = requests.post(
            response.json()["links"]["newversion"], headers=headers
        )
        response.raise_for_status()

        # Extract links from the response so we can be concise
        links = response.json()["links"]

        # Update the version of the new deposition
        logging.debug(f"Updating deposition with new version ({args.version})")
        metadata = response.json()["metadata"].copy()
        metadata["version"] = args.version

        response = requests.put(
            links["self"], data=json.dumps({"metadata": metadata}), headers=headers
        )
        response.raise_for_status()

        if args.files:
            # Remove the old file/s
            for file in response.json()["files"]:
                logging.debug(f"Removing old file - {file['filename']}")
                response = requests.delete(file["links"]["self"], headers=headers)
                response.raise_for_status()

            # Upload the new files for the deposition
            for i, filepath in enumerate(args.files):
                with open(filepath, "rb") as fp:
                    if args.filenames:
                        dest_filename = args.filenames[i]
                    else:
                        dest_filename = os.path.basename(filepath)

                    logging.debug(
                        f"Uploading file {filepath} with filename {dest_filename}"
                    )
                    response = requests.put(
                        f"{links['bucket']}/{dest_filename}", data=fp, headers=headers
                    )

                response.raise_for_status()

        if args.draft:
            logging.debug("Not publishing new version since --draft was used")
        else:
            # Publish the new deposition
            logging.debug("Publishing new version")
            response = requests.post(links["publish"], headers=headers)
            response.raise_for_status()

    except requests.HTTPError as e:
        print(e)
        print(response)
        print(response.json())

    logging.debug("Zenodo update completed")


if __name__ == "__main__":
    main()
