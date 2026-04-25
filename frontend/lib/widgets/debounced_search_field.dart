import 'dart:async';

import 'package:flutter/material.dart';

class DebouncedSearchField extends StatefulWidget {
  final void Function(String) onChanged;
  final Duration debounce;

  const DebouncedSearchField({
    super.key,
    required this.onChanged,
    this.debounce = const Duration(milliseconds: 300),
  });

  @override
  State<DebouncedSearchField> createState() => _DebouncedSearchFieldState();
}

class _DebouncedSearchFieldState extends State<DebouncedSearchField> {
  Timer? _timer;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _onChanged(String value) {
    _timer?.cancel();
    _timer = Timer(widget.debounce, () => widget.onChanged(value));
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      autofocus: true,
      decoration: const InputDecoration(
        prefixIcon: Icon(Icons.search),
        hintText: 'Buscar productos…',
        border: OutlineInputBorder(),
      ),
      onChanged: _onChanged,
    );
  }
}
