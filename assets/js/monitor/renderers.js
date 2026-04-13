(function () {
  const Monitor = window.Monitor;
  const { dom } = Monitor;

  Monitor.renderers = {
    renderMarketCard({ priceId, changeId, subId, sourceId, market, decimals, subHtmlBuilder, closedLabel = "休盘中" }) {
      if (!market || market.error) return;

      if (market.closed) {
        dom.setText(priceId, "—");
        dom.setClassName(priceId, "price-main");
        dom.setText(changeId, market.status_desc || closedLabel);
        dom.setClassName(changeId, "price-change");
        dom.setHtml(subId, "");
        dom.setText(sourceId, "休市");
        return;
      }

      const direction = (market.change || 0) >= 0 ? "up" : "down";
      const sign = (market.change || 0) >= 0 ? "+" : "";
      dom.setText(priceId, (market.price || 0).toFixed(decimals));
      dom.setClassName(priceId, "price-main " + direction);
      dom.setHtml(
        changeId,
        `${sign}${(market.change || 0).toFixed(decimals)} (${sign}${(market.changePercent || 0).toFixed(2)}%)`
      );
      dom.setClassName(changeId, "price-change " + direction);
      dom.setHtml(subId, subHtmlBuilder(market));
      dom.setText(sourceId, market.source || "--");
    },

    renderSpreadCard({ ratioId, statusId, detailId, spread, detailTextBuilder }) {
      if (!spread || !spread.ratio) return;
      dom.setText(ratioId, spread.ratio.toFixed(4));
      const statusNode = dom.setText(statusId, spread.status || "N/A");
      if (statusNode) {
        statusNode.className =
          "spread-status " +
          ((spread.status || "").includes("溢价") ? "premium" : (spread.status || "").includes("折价") ? "discount" : "balanced");
      }
      dom.setText(detailId, detailTextBuilder(spread));
    },

    renderAtrMetric({ valueId, barId, atrValue, decimals, unit, maxScale }) {
      dom.setText(valueId, atrValue ? atrValue.toFixed(decimals) + " " + unit : "--");
      dom.setStyle(barId, "width", Math.min(100, (atrValue / maxScale) * 100) + "%");
    },

    renderTickTable({ countId, bodyId, rows, priceDecimals }) {
      const formatTime = ts => new Date(ts).toLocaleTimeString("zh-CN", { hour12: false });
      dom.setText(countId, rows.length + " ticks");
      dom.setHtml(
        bodyId,
        rows
          .map(
            row =>
              `<tr><td>${formatTime(row.ts)}</td><td>${row.price.toFixed(priceDecimals)}</td><td class="pct ${row.pct > 0 ? "up" : row.pct < 0 ? "down" : ""}">${row.pct > 0 ? "+" : ""}${row.pct.toFixed(3)}%</td><td>${row.source}</td></tr>`
          )
          .join("")
      );
    },
  };
})();
