class Product {
  final String id;
  final String name;
  final String? brand;
  final String? offName;
  final String? offImageUrl;

  const Product({
    required this.id,
    required this.name,
    this.brand,
    this.offName,
    this.offImageUrl,
  });

  factory Product.fromJson(Map<String, dynamic> json) {
    return Product(
      id: json['id'] as String,
      name: json['name'] as String,
      brand: json['brand'] as String?,
      offName: json['off_name'] as String?,
      offImageUrl: json['off_image_url'] as String?,
    );
  }
}
