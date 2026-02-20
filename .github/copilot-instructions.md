# CloudShell — Copilot Coding Guidelines

> Project overview and architecture are documented in [README.md](../README.md).

## Language specification

- Strict NO EMOJI policy
- Test coverage for all new features and bug fixes

### Python

- Always use venv for virtual environments
  - Always activate the virtual environment before installing dependencies
  - Use requirements.txt to manage dependencies
- Use logging library with appropriate log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  - Use lazy formatting for log messages (e.g. logging.debug("Message: %s", variable))
- Follow PEP 8 style guide for Python code
- Use type hints for function signatures and variable declarations
- Always add docstrings to all public modules, functions, and classes

### Testing

- Create reusable GitHub workflow templates for common testing scenarios
- Use pytest for unit and integration tests
- Aim for 100% test coverage on new features
- Include tests for edge cases and error conditions
- Run tests on every merge request
