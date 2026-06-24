{
  pkgs,
  python3Packages,
}:
python3Packages.buildPythonPackage rec {
  pname = "fhlmi";
  format = "pyproject";
  version = "0.46.0";

  src = pkgs.fetchFromGitHub {
    owner = "Future-House";
    repo = "ldp";
    rev = "refs/tags/v${version}";
    hash = "sha256-zNqaZhuVzD1pc43E7jAo2XXYkETmK2rJ4UM652LKeAc=";
  };

  sourceRoot = "source/packages/lmi";

  propagatedBuildInputs = with python3Packages; [
    aiohttp
    coredis
    fhaviary
    limits
    litellm
    openai
    orjson
    pydantic
    tiktoken
    typing-extensions

    # optional
    tqdm
    types-tqdm
    # numpy
    # sentence-transformers
  ];

  # litellm in nixpkgs is newer than the upper bound, but should be compatible
  pythonRemoveDeps = [ "litellm" ];

  pythonImportsCheck = [ "lmi" ];

  meta = {
    description = "A client to provide LLM responses for FutureHouse applications";
    homepage = "https://github.com/Future-House/ldp/packages/lmi";
    license = pkgs.lib.licenses.asl20;
  };
}
