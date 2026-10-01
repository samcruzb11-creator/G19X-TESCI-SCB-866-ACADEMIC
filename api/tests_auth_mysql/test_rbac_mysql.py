"""Run the same HTTP authorization cases on a guarded, fresh MySQL schema."""
from tests_unit.test_rbac_unit import *  # noqa: F403 -- intentional shared contract suite
MYSQL_RBAC = True
