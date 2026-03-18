{ lib
, python3Packages
, wrapGAppsHook4
, gobject-introspection
, gtk4
, libadwaita
, rustPlatform
, pkg-config
}:

let
  daemon = rustPlatform.buildRustPackage {
    pname = "big-parental-daemon";
    version = "1.0.0";
    src = ./big-parental-daemon;
    cargoLock.lockFile = ./big-parental-daemon/Cargo.lock;
    nativeBuildInputs = [ pkg-config ];
  };
in
python3Packages.buildPythonApplication {
  pname = "big-parental-controls";
  version = "1.0.0";
  pyproject = true;
  src = ./.;

  build-system = [ python3Packages.hatchling ];

  nativeBuildInputs = [
    wrapGAppsHook4
    gobject-introspection
  ];

  buildInputs = [
    gtk4
    libadwaita
  ];

  propagatedBuildInputs = with python3Packages; [
    pygobject3
    pycairo
  ];

  dontWrapGApps = true;
  makeWrapperArgs = [ "\${gappsWrapperArgs[@]}" ];

  postInstall = ''
    install -Dm755 ${daemon}/bin/big-parental-daemon $out/bin/big-parental-daemon
    install -Dm644 big-parental-controls/usr/share/applications/*.desktop \
      -t $out/share/applications/
    install -Dm644 big-parental-controls/usr/share/icons/hicolor/scalable/apps/*.svg \
      -t $out/share/icons/hicolor/scalable/apps/
  '';

  meta = with lib; {
    description = "Parental controls for BigLinux";
    homepage = "https://github.com/biglinux/big-parental-controls";
    license = licenses.gpl3Plus;
    platforms = platforms.linux;
    mainProgram = "big-parental-controls";
  };
}
