## PopIt3 Project Checklist

**Completed:**

- [x] Write comprehensive README with architecture overview
- [x] Include architecture diagram in README
- [x] Document the LLM integration clearly
- [x] Add code examples/usage instructions
- [x] Add requirements.txt
- [x] Fix obvious bugs (booking logic, rowspan parsing, hallucination CV fix)

**Essential (Do Next):**

- [ ] Add crash/error alerts to web reports (visible indicator when pipeline fails)
- [ ] Save sample emails as debugging fixtures (real anonymised examples for manual testing)

**High Value:**

- [ ] Add proper Python package structure (pyproject.toml)
- [ ] Generate HTML report for applications (like job analysis report)
- [ ] Add AngelList/other job board integration
- [ ] Validation in reports — flag missing fields visually (e.g. job with no title)

**Nice to Have:**

- [ ] Add a simple web interface (FastAPI) [To serve email databases?]
- [ ] Add type hints throughout (with asserts)
- [ ] Ensure consistent code style (own style)
