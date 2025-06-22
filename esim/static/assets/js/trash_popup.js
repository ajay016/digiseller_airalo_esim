// =============== Trash Functionality ====================
(function () {
  document.addEventListener("DOMContentLoaded", function () {
    const deleteIcons = document.querySelectorAll(".trash-3");

    deleteIcons.forEach(function (icon) {
      icon.addEventListener("click", function (event) {
        event.preventDefault();

        const productRow = icon.closest("tr");

        Swal.fire({
          title: "Are you sure?",
          text: "Do you really want to delete the product?",
          showCancelButton: true,
          confirmButtonColor: "#16C7F9",
          cancelButtonColor: "#FC4438",
          confirmButtonText: "Yes, delete it!",
          imageUrl: "/cuba/cubaapp/static/assets/images/gif/trash.gif",
          imageWidth: 120,
          imageHeight: 120,
        }).then((result) => {
          if (result.isConfirmed) {
            productRow.remove();
          }
        });
      });
    });
  });
})();
