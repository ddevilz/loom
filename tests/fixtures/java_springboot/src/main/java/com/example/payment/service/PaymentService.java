package com.example.payment.service;

import com.example.payment.domain.Payment;
import com.example.payment.repository.PaymentRepository;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Optional;

@Service
public class PaymentService {
    private final PaymentRepository paymentRepository;
    private final List<PaymentProcessor<? extends Payment>> processors;

    @Autowired
    public PaymentService(PaymentRepository paymentRepository, 
                         List<PaymentProcessor<? extends Payment>> processors) {
        this.paymentRepository = paymentRepository;
        this.processors = processors;
    }

    public Payment processPayment(Payment payment) {
        PaymentProcessor processor = findProcessor(payment);
        if (processor != null) {
            processor.process(payment);
            return paymentRepository.save(payment);
        }
        throw new IllegalArgumentException("No processor found for payment type: " + payment.getType());
    }

    public Optional<Payment> findById(String id) {
        return paymentRepository.findById(id);
    }

    public List<Payment> findAll() {
        return paymentRepository.findAll();
    }

    private PaymentProcessor findProcessor(Payment payment) {
        return processors.stream()
                .filter(p -> p.canProcess(payment))
                .findFirst()
                .orElse(null);
    }
}
