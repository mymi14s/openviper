/* Inject a version banner at the top of every documentation page. */

(function () {
    var version = window.OPENVIPER_VERSION || "unknown";
    var banner = document.createElement("div");
    banner.className = "version-banner";
    banner.innerHTML = "OpenViper v" + version + ' &nbsp;|&nbsp; <a href="../index.html">All versions</a>';

    /* Insert as the first child of <body> so it appears at the very top. */
    document.body.insertBefore(banner, document.body.firstChild);
})();
