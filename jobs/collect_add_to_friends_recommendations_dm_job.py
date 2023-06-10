import sys
from pathlib import Path

from pyspark.sql.utils import CapturedException

# package
sys.path.append(str(Path(__file__).parent.parent))
from src.config import Config, EnableToGetConfig
from src.environ import DotEnvError, EnvironNotSet
from src.helper import S3ServiceError
from src.keeper import ArgsKeeper, SparkConfigKeeper
from src.logger import SparkLogger
from src.spark import DatamartCollector

config = Config("config.yaml")

logger = SparkLogger().get_logger(logger_name=__name__)


def main() -> ...:
    try:
        DATE = str(sys.argv[1])
        DEPTH = int(sys.argv[2])
        SRC_PATH = str(sys.argv[3])
        TGT_PATH = str(sys.argv[4])
        COORDS_PATH = str(sys.argv[5])
        PROCESSED_DTTM = str(sys.argv[6])

        if len(sys.argv) > 7:
            raise IndexError("Too many arguments for job submitting! Expected 6")

        keeper = ArgsKeeper(
            date=DATE,
            depth=DEPTH,
            src_path=SRC_PATH,
            tgt_path=TGT_PATH,
            coords_path=COORDS_PATH,
            processed_dttm=PROCESSED_DTTM,
        )

        if not keeper.coords_path:
            raise S3ServiceError(
                "We need 'coords_path' for this job! Please specify one in given 'ArgsKeeper' instance"
            )

    except (IndexError, S3ServiceError) as err:
        logger.error(err)
        sys.exit(1)

    conf = SparkConfigKeeper(
        executor_memory="3000m", executor_cores=1, max_executors_num=12
    )

    try:
        collector = DatamartCollector()
    except (DotEnvError, EnvironNotSet, EnableToGetConfig) as err:
        logger.error(err)
        sys.exit(1)

    try:
        for bucket in (keeper.src_path, keeper.tgt_path, keeper.coords_path):
            collector.check_s3_object_existence(key=bucket.split(sep="/")[2], type="bucket")  # type: ignore
    except S3ServiceError as err:
        logger.error(err)
        sys.exit(1)

    try:
        collector.init_session(
            app_name=config.get_spark_application_name,
            spark_conf=conf,
            log4j_level=config.log4j_level,  # type: ignore
        )
        collector.collect_add_to_friends_recommendations_dm(keeper=keeper)

    except CapturedException as err:
        logger.error(err)
        sys.exit(1)

    finally:
        collector.stop_session()  # type: ignore
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except Exception as err:
        logger.exception(err)
        sys.exit(1)
