from __future__ import annotations

import re
import sys
import time
from logging import getLogger
from os import environ, getenv
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Literal

import requests
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    InvalidSchema,
    InvalidURL,
    JSONDecodeError,
    MissingSchema,
    Timeout,
)

sys.path.append(str(Path(__file__).parent.parent.parent))
from src.base import BaseRequestHandler
from src.cluster.exceptions import YandexAPIError
from src.logger import SparkLogger


class DataProcCluster(BaseRequestHandler):
    """Class for manage DataProc Clusters. Sends requests to Yandex Cloud API.

    ## Notes
    To initialize Class instance you need to specify environment variables in `.env` or as a global environment variables.

    Required variables are: `YC_DATAPROC_CLUSTER_ID`, `YC_DATAPROC_BASE_URL`, `YC_OAUTH_TOKEN`

    See `.env.template` for mote details.

    At initializing moment will try to get IAM token from environment variables if no ones, sends request to Yandex Cloud API to get token and than sets to environ as `YC_IAM_TOKEN`.

    ## Examples
    Initialize Class instance:
    >>> cluster = DataProcCluster()

    Send request to start Cluster:
    >>> cluster.exec_command(command="start")

    If request was sent successfully we can check current Cluster status:
    >>> cluster.check_status(target_status="running")
    ... [2023-05-26 12:51:21] {src.cluster.cluster:133} INFO: Sending request to check Cluster status. Target status: running
    ... [2023-05-26 12:51:21] {src.cluster.cluster:156} INFO: Current cluster status is: STARTING
    ... [2023-05-26 12:51:41] {src.cluster.cluster:156} INFO: Current cluster status is: STARTING
    ... [2023-05-26 12:59:39] {src.cluster.cluster:160} INFO: Current cluster status is: RUNNING
    ... [2023-05-26 12:59:39] {src.cluster.cluster:165} INFO: The target status has been reached!
    """

    __slots__ = (
        "_IAM_TOKEN",
        "logger",
    )

    def __init__(
        self,
        *,
        max_retries: int = 10,
        retry_delay: int = 60,
        session_timeout: int = 60 * 2,
    ) -> None:
        super().__init__(
            max_retries=max_retries,
            retry_delay=retry_delay,
            session_timeout=session_timeout,
        )
        self.logger = (
            getLogger("aiflow.task")
            if self.config.environ == "airflow"
            else SparkLogger(level=self.config.get_logging_level["python"]).get_logger(
                name=f"{__name__}.{__class__.__name__}"
            )
        )

        if "YC_IAM_TOKEN" not in environ:
            self._get_iam_token()

        self._IAM_TOKEN = getenv("YC_IAM_TOKEN")

    def _get_iam_token(self) -> bool:  # type: ignore
        """
        Gets IAM token from Yandex Cloud API. If recieved, sets as `YC_IAM_TOKEN` environment variable.

        ## Returns
        `bool` : Returns True if got token and successfully set as environ variable

        ## Raises
        `YandexAPIError` : If unable to get IAM token or error occured while sending requests to API
        """

        self.logger.debug("Getting Yandex Cloud IAM token")

        self.logger.debug(f"Max retries: {self._MAX_RETRIES}")
        self.logger.debug(f"Delay between retries: {self._DELAY} secs")

        for _TRY in range(1, self._MAX_RETRIES + 1):
            try:
                self.logger.debug(f"Requesting API... Try: {_TRY}")
                response = requests.post(
                    url="https://iam.api.cloud.yandex.net/iam/v1/tokens",
                    json={"yandexPassportOauthToken": self._OAUTH_TOKEN},
                    timeout=self._SESSION_TIMEOUT,
                )
                response.raise_for_status()

            except (InvalidSchema, InvalidURL, MissingSchema) as err:
                raise YandexAPIError(
                    f"{err}. Check provided URL for POST request in '_get_iam_token' method"
                )

            except (HTTPError, ConnectionError, Timeout) as err:
                if _TRY == self._MAX_RETRIES:
                    raise YandexAPIError(str(err))
                else:
                    self.logger.warning(f"{err}. Retrying...")
                    time.sleep(self._DELAY)

                    continue

            if response.status_code == 200:
                self.logger.debug("Response received")

                try:
                    self.logger.debug("Decoding response")
                    response = response.json()

                except JSONDecodeError as err:
                    if _TRY == self._MAX_RETRIES:
                        raise YandexAPIError(str(err))
                    else:
                        self.logger.warning(f"{err}. Retrying...")
                        _TRY += 1
                        time.sleep(self._DELAY)

                        continue
                try:
                    # fmt: off
                    token_key = next(_ for _ in response.keys() if re.search("iamtoken", _, re.IGNORECASE))

                    # fmt: on
                    self.logger.debug("IAM token collected")
                    environ["YC_IAM_TOKEN"] = response[token_key]

                    return True

                except StopIteration:
                    if _TRY == self._MAX_RETRIES:
                        raise YandexAPIError(
                            "Unable to get IAM token from API response"
                        )
                    else:
                        self.logger.warning(
                            "Can't find IAM token key in API response. Retrying..."
                        )
                        time.sleep(self._DELAY)

                        continue

            else:
                if _TRY == self._MAX_RETRIES:
                    raise YandexAPIError("Unable to get IAM token")
                else:
                    self.logger.warning(
                        "Ops, seems like something went wrong. Retrying..."
                    )
                    time.sleep(self._DELAY)

                    continue

    def exec_command(self, command: Literal["start", "stop"]) -> bool:  # type: ignore
        """Sends request to Yandex Cloud API to execute Cluster command.

        ## Parameters
        `command` : Command to execute

        ## Raises
        `YandexAPIError` : If unable to get response or error occured while requesting API
        """
        self.logger.info(f"Sending request to execute Cluster command: '{command}'")

        self.logger.debug(f"Max retries: {self._MAX_RETRIES}")
        self.logger.debug(f"Delay between retries: {self._DELAY} secs")

        for _TRY in range(1, self._MAX_RETRIES + 1):
            try:
                self.logger.debug(f"Requesting... Try: {_TRY}")
                response = requests.post(
                    url=f"{self._BASE_URL}/{self._CLUSTER_ID}:{command}",
                    headers={"Authorization": f"Bearer {self._IAM_TOKEN}"},
                    timeout=self._SESSION_TIMEOUT,
                )
                response.raise_for_status()

            except (InvalidSchema, InvalidURL, MissingSchema) as err:
                raise YandexAPIError(
                    f"{err}. Please check 'YC_DATAPROC_BASE_URL' and 'YC_DATAPROC_CLUSTER_ID' environment variables"
                )

            except (HTTPError, ConnectionError, Timeout) as err:
                if _TRY == self._MAX_RETRIES:
                    raise YandexAPIError(str(err))

                self.logger.warning(f"{err}. Retrying...")
                time.sleep(self._DELAY)

                continue

            if response.status_code == 200:
                self.logger.debug("Response received")

                try:
                    self.logger.debug("Decoding response")
                    response = response.json()
                    self.logger.debug(f"{response=}")
                except JSONDecodeError as err:
                    self.logger.warning(str(err))
                    pass

                self.logger.info("Command in progress!")

                return True

            else:
                if _TRY == self._MAX_RETRIES:
                    raise YandexAPIError("Unable send request to Yandex Cloud API")

                self.logger.warning("Ops, seems like something went wrong. Retrying...")
                time.sleep(self._DELAY)

                continue

    def check_status(self, target_status: Literal["running", "stopped"]) -> bool:  # type: ignore
        """Sends request to check current Cluster status.

        Waits until Cluster status will be equal to `target_status`.

        ## Parameters
        `target_status` : The target Cluster status

        ## Raises
        `YandexAPIError` : If unable to get response or error occured while requesting API
        """
        self.logger.info(
            f"Checking current Cluster status. Target status: '{target_status.upper()}'"
        )

        self.logger.debug(f"Max retries: {self._MAX_RETRIES}")
        self.logger.debug(f"Delay between retries: {self._DELAY} secs")

        for _TRY in range(1, self._MAX_RETRIES + 1):
            try:
                self.logger.debug(f"Requesting... Try: {_TRY}")
                response = requests.get(
                    url=f"{self._BASE_URL}/{self._CLUSTER_ID}",
                    headers={"Authorization": f"Bearer {self._IAM_TOKEN}"},
                    timeout=self._SESSION_TIMEOUT,
                )
                response.raise_for_status()

            except (InvalidSchema, InvalidURL, MissingSchema) as err:
                raise YandexAPIError(
                    f"{err}. Please check 'YC_DATAPROC_BASE_URL' and 'YC_DATAPROC_CLUSTER_ID' environment variables"
                )

            except (HTTPError, ConnectionError, Timeout) as err:
                if _TRY == self._MAX_RETRIES:
                    raise YandexAPIError(str(err))
                else:
                    self.logger.warning(f"{err}. Retrying...")
                    time.sleep(self._DELAY)

                    continue

            if response.status_code == 200:
                self.logger.debug("Response recieved")

                try:
                    self.logger.debug("Decoding response")
                    response = response.json()
                    self.logger.debug(f"{response=}")

                except JSONDecodeError as err:
                    if _TRY == self._MAX_RETRIES:
                        raise YandexAPIError(str(err))
                    else:
                        self.logger.warning(f"{err}. Retrying...")
                        time.sleep(self._DELAY)

                        continue
                try:
                    # fmt: off
                    status_key = next(_ for _ in response.keys() if re.search("status", _, re.IGNORECASE))

                    # fmt: on
                    if status_key in response.keys():
                        self.logger.info(
                            f"Current cluster status: '{response[status_key]}'"
                        )
                        if response[status_key].strip().lower() == target_status:
                            self.logger.info("The target status has been reached!")

                            return True

                        else:
                            if _TRY == self._MAX_RETRIES:
                                raise YandexAPIError(
                                    "No more retries left to check Cluster status!\n"
                                    f"Last received status was: '{response[status_key]}'"
                                )
                            else:
                                self.logger.info("Not target yet. Retrying...")
                                time.sleep(self._DELAY)

                                continue

                except StopIteration:
                    if _TRY == self._MAX_RETRIES:
                        raise YandexAPIError("Unable to get 'status' from API response")
                    else:
                        self.logger.warning("No 'status' in API response. Retrying...")
                        time.sleep(self._DELAY)

                        continue

            else:
                if _TRY == self._MAX_RETRIES:
                    raise YandexAPIError("Unable to get 'status' from API response")
                else:
                    self.logger.warning(
                        "Ops, seems like something went wrong. Retrying..."
                    )
                    time.sleep(self._DELAY)

                    continue
