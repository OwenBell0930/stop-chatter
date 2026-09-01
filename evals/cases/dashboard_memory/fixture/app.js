const positions = ["沪深300", "现金"];

function renderPortfolio() {
  return positions.join(" / ");
}

function fetchWeather() {
  return { forecast: "sunny", temperature: 26 };
}

renderPortfolio();
fetchWeather();

