# Contributing to TeleSentry

We welcome contributions to TeleSentry! Here's how you can help:

## How to Contribute

1. **Fork the repository** and create your branch from `main`
2. **Install development dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-asyncio
   ```
3. **Make your changes** following the code style guidelines
4. **Test your changes** with the test suite
5. **Submit a pull request** with a clear description of your changes

## Code Style Guidelines

- Follow PEP 8 style guide
- Use descriptive variable and function names
- Add docstrings to all functions and classes
- Keep functions small and focused
- Use async/await for all I/O operations
- Add type hints where possible

## Testing

Run the test suite with:
```bash
pytest tests/
```

## Feature Requests

1. Check if the feature is already requested in issues
2. If not, create a new issue with:
   - Clear description of the feature
   - Use cases
   - Potential implementation details

## Bug Reports

1. Check if the bug is already reported in issues
2. If not, create a new issue with:
   - Steps to reproduce
   - Expected behavior
   - Actual behavior
   - Environment details (OS, Python version, etc.)

## Code of Conduct

- Be respectful to other contributors
- Provide constructive feedback
- Focus on the best outcome for the project
- Be open to different approaches

## License

By contributing to TeleSentry, you agree that your contributions will be licensed under the MIT License.
