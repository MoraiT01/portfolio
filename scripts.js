function animateButton() {
    var btn = document.getElementById("animationButton");
    btn.classList.add("animate");
    setTimeout(function(){ 
      btn.classList.remove("animate"); 
    }, 1000);
  }