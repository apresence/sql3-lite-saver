# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.99.1] - 2025-02-08

### Fixed
- Fixed bug in README.md example code
- Removed commented-out dead code (ConnectionLike Protocol) from pool.py

### Added
- Added `test_readme_examples.py` script to automatically validate README code examples

## [0.99.0] - 2025-02-08

### Added
- Initial release
- SQLite connection pooling with configurable pool size
- Automatic WAL (Write-Ahead Logging) mode enablement with checkpoint support
- Built-in retry logic with exponential backoff
- Optional Tenacity integration for advanced retry control
- Thread-safe and multiprocess-safe connection management
- Context manager support for automatic connection acquisition/release
- Comprehensive test suite
- CI/CD pipeline with GitHub Actions

[Unreleased]: https://github.com/apresence/sql3-lite-saver/compare/v0.99.1...HEAD
[0.99.1]: https://github.com/apresence/sql3-lite-saver/compare/v0.99.0...v0.99.1
[0.99.0]: https://github.com/apresence/sql3-lite-saver/releases/tag/v0.99.0
