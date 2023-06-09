from __future__ import annotations

import sys
import time
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

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
from src.logger import SparkLogger
from src.submitter.exceptions import (
    UnableToGetResponse,
    UnableToSendRequest,
    UnableToSubmitJob,
)

if TYPE_CHECKING:
    from typing import Literal

    from src.keeper import ArgsKeeper


class SparkSubmitter(BaseRequestHandler):
    """Sends request to Rest API upon Hadoop Cluster to submit Spark job.

    ## Notes
    To initialize instance of Class you need to specify `CLUSTER_API_BASE_URL` in `.env` or as a global environment variable.

    See `.env.template` for more details.

    ## Examples
    Initialize Class instance:
    >>> submitter = SparkSubmitter()

    Send request to submit 'users_info_datamart_job.py' job:
    >>> submitter.submit_job(job="users_info_datamart_job", keeper=keeper)
    """

    __slots__ = ("logger",)

    def __init__(
        self,
        *,
        max_retries: int = 3,
        retry_delay: int = 10,
        session_timeout: int = 60 * 60,
    ) -> None:
        """

        ## Parameters
        `max_retries` : Max retries to send request, by default 3\n
        `retry_delay` : Delay between retries in seconds, by default 10\n
        `session_timeout` : Session timeout in seconds, by default 60*60
        """
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

    def submit_job(self, job: Literal["collect_users_demographic_dm_job", "collect_events_total_cnt_agg_wk_mnth_dm_job", "collect_add_to_friends_recommendations_dm_job"], keeper: ArgsKeeper) -> bool:  # type: ignore
        """Sends request to API to submit Spark job in Hadoop Cluster.

        ## Parameters
        `job` : `Literal[str]`
            Name of submitting job
        `keeper` : `ArgsKeeper`
            Instance with Job arguments

        ## Returns
        `bool` :
            True if jobs was submitted successfully

        ## Raises
        `UnableToSendRequest` :
            If unable to send request to Cluster
        `UnableToGetResponse` :
            If unable to get or decode response
        `UnableToSubmitJob` :
            If operation failed while execution in Cluster
        """
        self.logger.info(f"Submiting '{job}' job")

        self.logger.info(f"Spark job args:\n{keeper}")

        for _TRY in range(1, self._MAX_RETRIES + 1):
            try:
                self.logger.debug(f"Requesting API. Try: {_TRY}")
                response = requests.post(
                    url=f"{self._CLUSTER_API_BASE_URL}/submit_{job}",
                    timeout=self._SESSION_TIMEOUT,
                    data=keeper.json(),
                )
                response.raise_for_status()
                break

            except Timeout as err:
                raise UnableToSendRequest(f"{err}. Unable to submit '{job}' job.")

            except (InvalidSchema, InvalidURL, MissingSchema) as err:
                raise UnableToSendRequest(
                    f"{err}. Please check 'CLUSTER_API_BASE_URL' environ variable"
                )

            except (HTTPError, ConnectionError) as err:
                if _TRY == self._MAX_RETRIES:
                    raise UnableToSendRequest(str(err))
                else:
                    self.logger.warning(f"{err}. Retrying...")
                    time.sleep(self._DELAY)

                    continue

        if response.status_code == 200:  # type: ignore
            self.logger.debug("Response received")

            try:
                self.logger.debug("Decoding response")
                response = response.json()  # type: ignore
                self.logger.debug(f"{response=}")

            except JSONDecodeError as err:
                raise UnableToGetResponse(f"{str(err)}. Posible failed to submit job.")

            if response.get("returncode") == 2:
                self.logger.info(
                    f"'{job}' job was submitted successfully! Results stored -> {keeper.tgt_path}"
                )

                self.logger.debug(f"Job stdout:\n{response.get('stdout')}")
                self.logger.debug(f"Job stderr:\n{response.get('stderr')}")
                return True

            elif response.get("returncode") == 1:
                self.logger.error(f"Job stdout:\n{response.get('stdout')}")
                self.logger.error(f"Job stderr:\n{response.get('stderr')}")

                raise UnableToSubmitJob(
                    f"Unable to submit '{job}' job! API returned 1 code. See job output in logs"
                )
            else:
                raise UnableToSubmitJob(
                    f"Unable to submit '{job}' job. API returned code -> {response.get('returncode')}"
                )
        else:
            raise UnableToGetResponse(
                f"Unable to submit '{job}' job. Something went wrong. API response status code -> {response.status_code}"  # type: ignore
            )
