# Contributing to AisleSense

Thank you for your interest in contributing to AisleSense! This document provides guidelines for contributing to the project.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members

## How to Contribute

### Reporting Bugs

If you find a bug, please create an issue with:
- A clear, descriptive title
- Steps to reproduce the issue
- Expected vs. actual behavior
- Your environment (OS, ROS version, Python version)
- Relevant logs or screenshots

### Suggesting Enhancements

Enhancement suggestions are welcome! Please:
- Use a clear, descriptive title
- Provide a detailed description of the proposed feature
- Explain why this enhancement would be useful
- Include mockups or examples if applicable

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Follow the existing code style**:
   - Use meaningful variable names
   - Add docstrings to functions and classes
   - Follow PEP 8 for Python code
   - Keep lines under 88 characters (Black formatter default)

3. **Test your changes**:
   - Ensure existing functionality still works
   - Test on the target hardware if modifying robot code
   - Verify ONNX models load correctly if changing vision pipeline

4. **Document your changes**:
   - Update README.md if adding features
   - Add comments for complex logic
   - Update docstrings if changing function signatures

5. **Commit with clear messages**:
   ```
   feat: add gap severity color coding
   fix: resolve AMCL initialization bug
   docs: update Nav2 parameter descriptions
   ```

6. **Submit your PR** with:
   - Description of changes
   - Issue number it addresses (if applicable)
   - Screenshots/videos for visual changes

## Development Setup

### Robot Core (aislesense/)
```bash
cd aislesense
docker-compose build
docker-compose up
```

### Navigator GUI (aislesense_navigator/)
```bash
cd aislesense_navigator
pip install -r requirements.txt
python app.py
```

### Vision Analytics (asvision/)
```bash
cd asvision
pip install -r requirements.txt

# Download models (see Model Downloads section in README)
streamlit run app.py
```

## Model Files

ONNX model files are not stored in Git due to their size. Contributors should:
- Download models using the instructions in the main README
- Never commit `.onnx` files to the repository
- Document any changes to model loading or preprocessing

## Project Structure

- `aislesense/` — ROS 2 robot core
- `aislesense_navigator/` — Desktop navigation GUI
- `asvision/` — Vision inference pipeline

Each module has its own README with specific documentation.

## License

By contributing, you agree that your contributions will be licensed under the project's CC BY-NC 4.0 license.

## Questions?

Feel free to open an issue for any questions about contributing!
