# CloudShell — Copilot Coding Guidelines

> Project overview and architecture are documented in [README.md](../README.md).

## Language specification

- Strict NO EMOJI policy
- Strict NO EM-DASH policy
- Test coverage for all new features and bug fixes
- Keep files as small as possible, split components into separate files to improve readability and maintainability.

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
- Aim for 100% test coverage on every piece of code
- Include tests for edge cases and error conditions
- Run tests on every merge request
- When performing tests on the dev machine, prefer writing them as scripts and running them from the command line instead of plain text inline commands
- Every feature should have dedicated tests in the tests folder of the project
- Ensure smoke tests are available for all private and public APIs
- Ensure all tests (both frontend and backend) are run in a consistent environment (e.g. using Docker)
- Ensure all tests (both frontend and backend) are run at every pull request creation or update

## Security considerations

- Always encrypt sensitive data like credentials and keys
- Configure all apps to run on the least privileged user
- Implement rate limiting and monitoring for all APIs
- Isolate all functions and services to minimize the attack surface
  - Isolation is achieved by having a microservices architecture with backend on a different container from the frontend
- Ensure all APIs are protected with authentication and authorization
  - Only exception are login and health endpoints

## Backward compatibility

- Ensure that any changes to the API are backward compatible
- Deprecate old endpoints and provide clear migration paths for users
- Provide an upgrade path from old database schemas to new ones

## Documentation

- Every new feature should be documented in the README.md (or in one of the referenced markdown files) with clear instructions on how to use it
- Every new feature should be documented in the index.html file of the website folder with a dedicated feature tile

## Connections security

- At first connection to a new host, the user should be prompted to verify the host's fingerprint before proceeding with the connection
- The fingerprint should be displayed in a clear and easily understandable format, such as a hexadecimal string
- The user should have the option to save the host's fingerprint for future connections, but this should be an explicit choice and not the default behavior
- If the user chooses to save the fingerprint, it should be stored securely and associated with the host's address
- If the user chooses not to save the fingerprint, they should be prompted to verify it again on the next connection attempt
- If the fingerprint does not match the saved value on subsequent connections, the user should be alerted and given the option to proceed or abort the connection
  - If the user chooses to proceed, the new fingerprint should be saved and associated with the host's address, replacing the old value
  - If the user chooses to abort, the connection should be terminated immediately and no changes should be made to the saved fingerprint
- The user should have the option to view and manage their saved fingerprints, including the ability to delete them if they are no longer needed or if they want to reset their trusted hosts list
