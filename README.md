# XRPL controller module

## Getting Started
### Pre-Requisites
- Install Python 3.12

### Linux
```console
user@laptop:~$ git clone git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-controller-module.git
user@laptop:~$ cd xrpl-controller-module
user@laptop:~$ python -m venv .venv               # Recommended: create a virtual environment
user@laptop:~$ source .venv/bin/activate          # Activate the virtual env
user@laptop:~$ pip install -r requirements.txt    # Install requirements
user@laptop:~$ tox                                # Runs pipeline locally (without documentation generation)
user@laptop:~$ python3 -m xrpl_controller         # Runs the application
```


### Windows
```console
PS > git clone git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-controller-module.git
PS > cd xrpl-controller-module
PS > python -m venv .venv               # Recommended: create a virtual environment
PS > ./.venv/Scripts/activate           # Activate the virtual env
PS > pip install -r requirements.txt    # Install requirements
PS > tox                                # Runs pipeline locally (without documentation generation)
PS > python3 -m xrpl_controller         # Runs the application
```

I recommend creating a Virtual Environment using the command (executed in the root of the repository): `python -m venv .venv` This command will create a virtual environment in a subfolder `.venv`, pyCharm should automatically pick this up and use it by default.

## The pipeline
Current included stages:
- Unit testing using [pytest](https://docs.pytest.org/en/8.2.x/)
- Linting using [ruff](https://docs.astral.sh/ruff/)
- Type checking using [mypy](https://mypy.readthedocs.io/en/stable/)
- Style checking/formatting using [ruff](https://docs.astral.sh/ruff/)
- Automatic documentation generation using [Sphinx](https://www.sphinx-doc.org) and [Read-the-Docs](https://docs.readthedocs.io/en/stable/)

### Unit Testing & Static Analysis
To run the different pipeline stages, excluding the automatic documentation generation, I opted for [tox](https://tox.wiki/en/4.15.0/user_guide.html).
`tox` makes sure every stage of the pipeline runs in a separate environment, which eliminates interference. Another benefit of `tox` is the ability to execute the `tox` command in a local terminal, which will run unit testing, type checking, linting and style checking locally, meaning you do not have to push your changes to GitLab to check whether the pipeline will fail or pass.

### Documentation Generation
The automated documentation generation will only run on a merge to main. After successful execution, it will publish the generated HTML on [GitLab Pages](https://docs.gitlab.com/ee/user/project/pages/) automatically, which means the most recent version of the documentation will always be available through our repository.


## How to generate documentation

### Linux
```console
user@laptop:~$ cd docs
user@laptop:~$ make clean && make html
```

### Windows
```console
PS > cd docs
PS > ./make.bat clean
PS > ./make.bat html
```

The documentation website files should now be in `docs/_build/html`. Then, inside this folder, you can open `index.html` with your browser.
