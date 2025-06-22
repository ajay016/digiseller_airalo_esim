(function () {
  var primary = localStorage.getItem("primary") || "#7366FF";
  var secondary = localStorage.getItem("secondary") || "#838383";

  window.CubaAdminConfig = {
    // Theme Primary Color
    primary: primary,
    // theme secondary color
    secondary: secondary,
  };
})();
