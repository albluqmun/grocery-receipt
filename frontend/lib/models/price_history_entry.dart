class PriceHistoryEntry {
  final DateTime date;
  final String supermarketName;
  final double unitPrice;

  const PriceHistoryEntry({
    required this.date,
    required this.supermarketName,
    required this.unitPrice,
  });

  factory PriceHistoryEntry.fromJson(Map<String, dynamic> json) {
    return PriceHistoryEntry(
      date: DateTime.parse(json['date'] as String),
      supermarketName: json['supermarket_name'] as String,
      unitPrice: double.parse(json['unit_price'].toString()),
    );
  }
}
