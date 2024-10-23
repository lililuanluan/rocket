## Testing

The testing of the Controller Module is split between integration, system level and unit testing. 
It is then able to generate testing reports, to visualise the quality of the program and how well tested it is.


### System-level Automated Testing
We have included some system-level automated tests. These can be run using `python -m tests.system_level`. Make sure Docker is running before you start the tests, to ensure correct execution.

### Generating testing reports
To generate testing reports, you can run the following command:
```console
pytest tests/ --cov=xrpl_controller --cov-branch --cov-report json:coverage_reports/coverage.json --ignore=tests/system_level
python coverage_script.py
```
You can specify which tests to run by changing the path in the first command, for example to only run the unit tests you can use `tests/unit/`.
To produce the actual interactive report, you need to run the pytest command with the additional argument `--cov-report html:coverage_reports/html/` which will generate a html report in the `coverage_reports/html/` directory.
If you want to generate a coverage report for the system tests, you can use the IDE "Run with Coverage" option with the custom run configuration for systems tests that is specified in the section above.
