# Contributing to FafyCat

Thank you for your interest in contributing to FafyCat! We welcome contributions from everyone who wants to help make personal finance management more accessible and privacy-focused.

## Code of Conduct

By participating in this project, you agree to be respectful and constructive in all interactions. We aim to create a welcoming environment for contributors of all backgrounds and experience levels.

## How to Contribute

### Reporting Issues

1. **Search existing issues** to avoid duplicates
2. **Use issue templates** when available
3. **Provide context**: Include OS, Python version, and steps to reproduce
4. **Be specific**: Clear descriptions help us fix issues faster

### Suggesting Features

1. **Check the roadmap** in existing issues and discussions
2. **Explain the use case**: Why would this feature be valuable?
3. **Consider privacy**: All features must maintain local-only processing
4. **Be patient**: Features are prioritized by community benefit

### Contributing Code

#### Setup Development Environment

```bash
# Fork and clone the repository
git clone https://github.com/yourusername/fafycat.git
cd fafycat

# Create a virtual environment
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
uv install

# Run tests to verify setup
uv run pytest
```

#### Development Workflow

1. **Create a branch** for your feature/fix:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes** following our coding standards

3. **Run quality checks**:
   ```bash
   # Format code
   uvx ruff format
   
   # Check linting
   uvx ruff check
   
   # Type checking
   uv run mypy
   
   # Run tests
   uv run pytest
   ```

4. **Write tests** for new functionality

5. **Update documentation** if needed

6. **Commit with clear messages**:
   ```bash
   git commit -m "feat: add new export format"
   git commit -m "fix: correct transaction deduplication"
   ```

7. **Push and create a Pull Request**

#### Coding Standards

- **Python 3.13+** compatible code
- **Type hints** for all functions
- **Docstrings** for public APIs
- **Line length**: 120 characters max
- **Test coverage** for new features
- **No external API calls** (privacy first!)

#### Commit Message Format

We follow conventional commits:

- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `style:` Code style changes
- `refactor:` Code refactoring
- `test:` Test additions/changes
- `chore:` Maintenance tasks

### Testing Guidelines

- Write tests for all new functionality
- Place tests in `tests/` directory
- Use descriptive test names
- Mock external dependencies
- Ensure tests are deterministic

### Documentation

- Update README.md for user-facing changes
- Add docstrings to new functions/classes
- Include examples in documentation
- Keep language clear and concise

## Pull Request Process

1. **Fill out the PR template** completely
2. **Link related issues** using keywords (fixes #123)
3. **Ensure CI passes** all checks
4. **Respond to feedback** promptly
5. **Be patient** with the review process

### PR Requirements

- [ ] Code follows project style guidelines
- [ ] Tests pass locally and in CI
- [ ] Documentation is updated
- [ ] No hardcoded paths or personal data
- [ ] Changes maintain privacy-first approach

## Development Tips

### Common Tasks

```bash
# Run in development mode
uv run python run_dev.py

# Reset with sample data
uv run python scripts/reset_and_import.py --dev-mode --use-sample-data

# Train model with test data
uv run python scripts/train_model.py

# Check API documentation
# http://localhost:8000/docs
```

### Debugging

- Enable SQL logging: `FAFYCAT_DB_ECHO=true`
- Check logs in development mode
- Use FastAPI's interactive docs
- Add print statements (remove before PR)

## Getting Help

- **Discord**: [Join our community](https://discord.gg/fafycat) (if available)
- **Discussions**: Use GitHub Discussions for questions
- **Issues**: For bugs and feature requests
- **Email**: contributors@fafycat.org (if available)

## Recognition

Contributors are recognized in:
- The repository's Contributors page
- Release notes for significant contributions
- Special thanks in documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for helping make FafyCat better for everyone! =1