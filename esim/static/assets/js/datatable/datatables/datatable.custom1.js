(function ($) {
  $(document).ready(function () {
    // // Setup - add a text input to each footer cell

    //single row delete data table start here
    var deleterow = $("#row-select-delete").DataTable();
    $("#row-select-delete tbody").on("click", "tr", function () {
      if ($(this).hasClass("selected")) {
        $(this).removeClass("selected");
      } else {
        deleterow.$("tr.selected").removeClass("selected");
        $(this).addClass("selected");
      }
    });
    //single row delete data table end here

    //Range plugin datatable start here
    $.fn.dataTable.ext.search.push(function (settings, data, dataIndex) {
      var min = parseInt($("#min").val(), 10);
      var max = parseInt($("#max").val(), 10);
      var age = parseFloat(data[3]) || 0;
      if ((isNaN(min) && isNaN(max)) || (isNaN(min) && age <= max) || (min <= age && isNaN(max)) || (min <= age && age <= max)) {
        return true;
      }
      return false;
    });
    var dtage = $("#datatable-range").DataTable();
    $("#min, #max").keyup(function () {
      dtage.draw();
    });
    //Range plugin datatable end here
  });
  /* Formatting function for row details - modify as you need */
  function format(d) {
    // `d` is the original data object for the row
    return '<table cellpadding="5" cellspacing="0" border="0" style="padding-left:50px;">' + "<tr>" + "<td>Full name:</td>" + "<td>" + d.name + "</td>" + "</tr>" + "<tr>" + "<td>Extension number:</td>" + "<td>" + d.extn + "</td>" + "</tr>" + "<tr>" + "<td>Extra info:</td>" + "<td>And any further details here (images etc)...</td>" + "</tr>" + "</table>";
  }
})(jQuery);
