{
  pkgs,
  python3Packages,
}:
python3Packages.buildPythonPackage rec {
  pname = "paper-qa";
  version = "5.29.1";

  format = "pyproject";

  src = pkgs.fetchFromGitHub {
    owner = "Future-House";
    repo = "${pname}";
    rev = "refs/tags/v${version}";
    hash = "sha256-h+z/8CUNekgjH3x7fO0OkeUU7d8asWEgbQIZmCn8ijo=";
  };

  propagatedBuildInputs = with python3Packages; [
    aiohttp
    anyio
    fhlmi
    fhaviary
    html2text
    httpx
    numpy
    pybtex
    pydantic-settings
    pydantic
    rich
    setuptools
    tantivy
    tenacity
    tiktoken
  ];

  # NOTE: to handle circular dependency between paper-qa and paper-qa-pypdf
  pythonRemoveDeps = [ "paper-qa-pypdf" ];
  passthru.optional-dependencies = {
    paper-qa-pypdf = [ python3Packages.paper-qa-pypdf ];
  };

  # NOTE: Disabled since it causes "> PermissionError: [Errno 13] Permission denied: '/homeless-shelter'"
  # pythonImportsCheck = ["paperqa"];

  meta = {
    homepage = "https://github.com/Future-House/paper-qa";
    description = "LLM Chain for answering questions from docs";
    license = pkgs.lib.licenses.asl20;
  };
}
